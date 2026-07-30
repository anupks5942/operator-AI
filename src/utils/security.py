"""
PCI-DSS helpers: mask payment card numbers (PAN) and block prohibited card auth data.
"""
import re
import os
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)


async def verify_api_key(
    api_key: str = Security(api_key_header),
):
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

# Visa / Mastercard / Discover-style 16-digit PAN (with optional spaces or hyphens).
_VISA_MC_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")

# American Express 15-digit PAN.
_AMEX_PATTERN = re.compile(r"\b3[47]\d{2}[ -]?\d{6}[ -]?\d{5}\b")

# Keywords for data that must never be collected (PCI forbidden storage).
_PCI_AUTH_KEYWORDS = (
    "cvv",
    "cvc",
    "cvc2",
    "cvv2",
    "security code",
    "card verification",
    "verification code on the back",
    "track 1",
    "track 2",
    "track data",
    "magnetic stripe",
    "mag stripe",
    "pin block",
)

_CVV_VALUE_PATTERN = re.compile(
    r"\b(?:cvv|cvc|security code)\s*(?:is|:)?\s*\d{3,4}\b",
    re.IGNORECASE,
)


def mask_credit_cards(text: str) -> str:
    """Replace PAN-like sequences with last-4-only masked form."""
    if not text:
        return text

    def _replace(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 13:
            return match.group(0)
        return f"**-**-****-{digits[-4:]}"

    scrubbed = _VISA_MC_PATTERN.sub(_replace, text)
    scrubbed = _AMEX_PATTERN.sub(_replace, scrubbed)
    return scrubbed


def contains_prohibited_card_auth_data(text: str) -> bool:
    """
    True when the user message appears to provide or request CVV, track data, or similar.
    Loyalty card numbers and last-4 references are not matched.
    """
    if not text:
        return False
    lower = text.lower()
    if any(keyword in lower for keyword in _PCI_AUTH_KEYWORDS):
        return True
    return bool(_CVV_VALUE_PATTERN.search(lower))


def sanitize_user_text(text: str) -> str:
    """
    Single ingress point for operator plain-text: mask PAN before graph, LLM, logs, or storage.
    """
    return mask_credit_cards(text)


def sanitize_outbound_text(text: str) -> str:
    """Mask PAN in text leaving the system (escalation email/SMS, ticket summaries)."""
    return mask_credit_cards(text)
