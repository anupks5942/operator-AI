from __future__ import annotations

import html
import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.utils.security import sanitize_outbound_text
from src.config import (
    ESCALATION_EMAIL,
    ESCALATION_SMS_TO,
    FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    USE_LIVE_NOTIFICATIONS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EscalationResult:
    email_sent: bool
    sms_sent: bool


class NotificationService:
    @staticmethod
    def send_sms(to_number: str, message: str) -> bool:
        if not USE_LIVE_NOTIFICATIONS:
            logger.info("[Mock Twilio SMS] Sending to %s: %s", to_number, message)
            print(f"[Mock Twilio SMS] Sending to {to_number}: {message}")
            return True

        if not all((TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, to_number)):
            logger.error("Twilio SMS skipped: missing credentials or destination number")
            return False

        try:
            from twilio.rest import Client

            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                from_=TWILIO_FROM_NUMBER,
                to=to_number,
                body=message,
            )
            logger.info("Twilio SMS sent to %s", to_number)
            return True
        except Exception as exc:
            logger.exception("Twilio SMS failed: %s", exc)
            return False

    @staticmethod
    def send_email_html(to_email: str, subject: str, html_body: str) -> bool:
        if not USE_LIVE_NOTIFICATIONS:
            logger.info(
                "[Mock Email] To %s | Subject: %s | Body length: %d",
                to_email,
                subject,
                len(html_body),
            )
            print(f"[Mock Email] To {to_email} | Subject: {subject}")
            return True

        if not all((SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, FROM_EMAIL, to_email)):
            logger.error("SMTP email skipped: missing credentials or destination address")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = FROM_EMAIL
            msg["To"] = to_email
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

            logger.info("Escalation email sent to %s", to_email)
            return True
        except smtplib.SMTPException as exc:
            logger.exception("SMTP email failed: %s", exc)
            return False

    @staticmethod
    def send_email(to_email: str, subject: str, body: str) -> bool:
        """Plain-text email wrapper for legacy /notify endpoints."""
        escaped = html.escape(body)
        html_body = f"<html><body><pre>{escaped}</pre></body></html>"
        return NotificationService.send_email_html(to_email, subject, html_body)

    @staticmethod
    def _build_escalation_html(
        *,
        name: str,
        email: str,
        phone: str,
        conversation: str,
    ) -> str:
        safe_name = html.escape(name)
        safe_email = html.escape(email)
        safe_phone = html.escape(phone)
        safe_conversation = html.escape(conversation)
        return f"""
        <html>
            <body>
                <h2>New Escalation Request</h2>
                <p><strong>Name:</strong> {safe_name}</p>
                <p><strong>Email:</strong> {safe_email}</p>
                <p><strong>Phone:</strong> {safe_phone}</p>
                <h3>Conversation History</h3>
                <pre>{safe_conversation}</pre>
            </body>
        </html>
        """

    @staticmethod
    def send_escalation(
        *,
        ticket_id: str,
        name: str,
        email: str,
        phone: str,
        conversation: str,
        summary: str,
    ) -> EscalationResult:
        safe_conversation = sanitize_outbound_text(conversation)
        safe_summary = sanitize_outbound_text(summary)
        subject = f"SpyderWash Operator Escalation - {name}"
        html_body = NotificationService._build_escalation_html(
            name=name,
            email=email,
            phone=phone,
            conversation=safe_conversation,
        )
        email_sent = NotificationService.send_email_html(ESCALATION_EMAIL, subject, html_body)

        sms_body = f"SpyderWash ESCALATION {ticket_id}: {safe_summary[:140]}"
        sms_sent = NotificationService.send_sms(ESCALATION_SMS_TO, sms_body)

        if not email_sent:
            logger.warning("Escalation email dispatch failed for ticket %s", ticket_id)
        if not sms_sent:
            logger.warning("Escalation SMS dispatch failed for ticket %s", ticket_id)

        return EscalationResult(email_sent=email_sent, sms_sent=sms_sent)
