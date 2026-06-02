import logging

logger = logging.getLogger(__name__)

class NotificationService:
    @staticmethod
    def send_sms(to_number: str, message: str) -> bool:
        """
        Mock sending an SMS via Twilio.
        """
        logger.info(f"[Mock Twilio SMS] Sending to {to_number}: {message}")
        print(f"[Mock Twilio SMS] Sending to {to_number}: {message}")
        return True

    @staticmethod
    def send_email(to_email: str, subject: str, body: str) -> bool:
        """
        Mock sending an Email.
        """
        logger.info(f"[Mock Email] To {to_email} | Subject: {subject} | Body: {body}")
        print(f"[Mock Email] To {to_email} | Subject: {subject} | Body: {body}")
        return True
