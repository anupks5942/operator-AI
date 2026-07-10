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
        ticket_id: str,
        name: str,
        email: str,
        phone: str,
        conversation: str,
        summary: str,
    ) -> str:
        from datetime import datetime, timezone

        safe_ticket = html.escape(ticket_id)
        safe_summary = html.escape(summary)
        safe_conversation = html.escape(conversation)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        is_critical = "entire location" in summary.lower() or "Critical" in summary
        severity_label = "CRITICAL" if is_critical else "STANDARD"
        severity_color = "#dc3545" if is_critical else "#fd7e14"

        # Operator contact section — only rendered when real data is available
        contact_section = ""
        has_real_contact = (
            name and "Unknown" not in name
            and email and "unknown@" not in email
        )
        if has_real_contact:
            safe_name = html.escape(name)
            safe_email = html.escape(email)
            safe_phone = html.escape(phone)
            contact_section = f"""
                <tr>
                    <td style="padding:16px 24px; border-bottom:1px solid #e9ecef;">
                        <h3 style="margin:0 0 8px 0; color:#495057; font-size:14px; text-transform:uppercase; letter-spacing:0.5px;">Operator Contact</h3>
                        <p style="margin:4px 0;"><strong>Name:</strong> {safe_name}</p>
                        <p style="margin:4px 0;"><strong>Email:</strong> {safe_email}</p>
                        <p style="margin:4px 0;"><strong>Phone:</strong> {safe_phone}</p>
                    </td>
                </tr>
            """

        return f"""
        <html>
        <body style="margin:0; padding:0; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#f8f9fa;">
            <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px; margin:24px auto; background:#ffffff; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
                <!-- Header -->
                <tr>
                    <td style="padding:24px; background:#1a1a2e; border-radius:8px 8px 0 0;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                                <td>
                                    <h1 style="margin:0; color:#ffffff; font-size:18px;">SpyderWash Escalation</h1>
                                    <p style="margin:4px 0 0 0; color:#adb5bd; font-size:13px;">Ticket: {safe_ticket} | {timestamp}</p>
                                </td>
                                <td align="right">
                                    <span style="display:inline-block; padding:4px 12px; background:{severity_color}; color:#fff; border-radius:4px; font-size:12px; font-weight:600;">{severity_label}</span>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
                <!-- Technical Summary -->
                <tr>
                    <td style="padding:24px; border-bottom:1px solid #e9ecef;">
                        <h3 style="margin:0 0 12px 0; color:#495057; font-size:14px; text-transform:uppercase; letter-spacing:0.5px;">Technical Summary</h3>
                        <pre style="margin:0; padding:16px; background:#f8f9fa; border-radius:6px; font-family:'SF Mono', Consolas, monospace; font-size:13px; line-height:1.6; white-space:pre-wrap; word-wrap:break-word; color:#212529;">{safe_summary}</pre>
                    </td>
                </tr>
                <!-- Operator Contact (conditional) -->
                {contact_section}
                <!-- Full Transcript -->
                <tr>
                    <td style="padding:16px 24px;">
                        <h3 style="margin:0 0 8px 0; color:#495057; font-size:14px; text-transform:uppercase; letter-spacing:0.5px;">Full Conversation Transcript</h3>
                        <pre style="margin:0; padding:16px; background:#f8f9fa; border-radius:6px; font-family:'SF Mono', Consolas, monospace; font-size:12px; line-height:1.5; white-space:pre-wrap; word-wrap:break-word; color:#6c757d; max-height:400px; overflow-y:auto;">{safe_conversation}</pre>
                    </td>
                </tr>
                <!-- Footer -->
                <tr>
                    <td style="padding:16px 24px; background:#f8f9fa; border-radius:0 0 8px 8px; text-align:center;">
                        <p style="margin:0; color:#6c757d; font-size:11px;">Auto-generated by SpyderWash Operator AI | Do not reply to this email</p>
                    </td>
                </tr>
            </table>
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
        is_critical = "entire location" in safe_summary.lower() or "Critical" in safe_summary
        severity_tag = "[CRITICAL]" if is_critical else "[STANDARD]"
        subject = f"{severity_tag} SpyderWash Escalation {ticket_id}"
        html_body = NotificationService._build_escalation_html(
            ticket_id=ticket_id,
            name=name,
            email=email,
            phone=phone,
            conversation=safe_conversation,
            summary=safe_summary,
        )
        email_sent = NotificationService.send_email_html(ESCALATION_EMAIL, subject, html_body)

        sms_issue = safe_summary.split("\n")[0].replace("ISSUE: ", "")[:120]
        sms_body = f"SpyderWash {severity_tag} {ticket_id}: {sms_issue}"
        sms_sent = NotificationService.send_sms(ESCALATION_SMS_TO, sms_body)

        if not email_sent:
            logger.warning("Escalation email dispatch failed for ticket %s", ticket_id)
        if not sms_sent:
            logger.warning("Escalation SMS dispatch failed for ticket %s", ticket_id)

        return EscalationResult(email_sent=email_sent, sms_sent=sms_sent)
