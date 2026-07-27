"""
App settings live here.

We read values from the .env file once, then the rest of the app imports them.
Tools should take API URLs from here — do not hardcode them elsewhere.
"""
import os

from dotenv import load_dotenv

# Read the .env file into the environment before we look up any settings.
load_dotenv()


def _env_str(name: str, default: str) -> str:
    """
    Get a text setting from .env.

    If it is missing or blank, use the default instead.
    """
    value = os.getenv(name, default).strip()
    return value or default


def _env_bool(name: str, default: bool) -> bool:
    """
    Get a yes/no setting from .env.

    Values like false, 0, or no mean False. Anything else that is set means True.
    If the setting is missing, use the default.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no")


# Where the live Setomatic website API lives (loyalty, transactions, kiosk, etc.).
SETOMATIC_BASE_URL: str = os.getenv(
    "SETOMATIC_BASE_URL",
    "https://betasetomaticposwebapplication.spyderwash.com",
)

# Which AI company to use for chat: "openai" or "groq".
LLM_PROVIDER: str = _env_str("LLM_PROVIDER", "openai").lower()
# Which OpenAI chat model to use when provider is openai.
OPENAI_MODEL: str = _env_str("OPENAI_MODEL", "gpt-4o-mini")
# Which Groq chat model to use when provider is groq.
GROQ_MODEL: str = _env_str("GROQ_MODEL", "llama-3.3-70b-versatile")

# Model that turns KB text into vectors for search. If you change this, delete chroma_db and restart.
OPENAI_EMBEDDING_MODEL: str = _env_str("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# False = only print/log emails and SMS (safe for local). True = really send them.
USE_LIVE_NOTIFICATIONS: bool = _env_bool("USE_LIVE_NOTIFICATIONS", False)

# Twilio login details for SMS (needed only when live notifications are on).
TWILIO_ACCOUNT_SID: str = _env_str("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = _env_str("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER: str = _env_str("TWILIO_FROM_NUMBER", "")
# Phone number that receives the emergency SMS.
ESCALATION_SMS_TO: str = _env_str("ESCALATION_SMS_TO", "")

# Email (SMTP) settings for Mandrill — used for support tickets.
SMTP_HOST: str = _env_str("SMTP_HOST", "smtp.mandrillapp.com")
SMTP_PORT: int = int(_env_str("SMTP_PORT", "587"))
SMTP_USERNAME: str = _env_str("SMTP_USERNAME", "")
SMTP_PASSWORD: str = _env_str("SMTP_PASSWORD", "")
# "From" address on ticket emails.
FROM_EMAIL: str = _env_str("FROM_EMAIL", "support@spyderwash.com")
# Inbox that receives the ticket emails.
ESCALATION_EMAIL: str = _env_str("ESCALATION_EMAIL", "support@setomaticsystems.com")
