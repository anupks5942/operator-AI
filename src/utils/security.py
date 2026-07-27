"""
Safety helpers for payment card data (PCI rules).

Simple jobs:
  1) Hide full card numbers before they go to the AI.
  2) Spot CVV / track data so we can refuse those messages.
  3) Hide card numbers again in outbound emails/SMS.
"""
import re

# Finds normal 16-digit card numbers (Visa / Mastercard style).
_VISA_MC_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")

# Finds 15-digit Amex card numbers.
_AMEX_PATTERN = re.compile(r"\b3[47]\d{2}[ -]?\d{6}[ -]?\d{5}\b")

# Words that mean the user is talking about CVV / track / PIN (not allowed in chat).
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

# Catches things like "cvv: 123" even if worded a bit differently.
_CVV_VALUE_PATTERN = re.compile(
    r"\b(?:cvv|cvc|security code)\s*(?:is|:)?\s*\d{3,4}\b",
    re.IGNORECASE,
)


def mask_credit_cards(text: str) -> str:
    """
    Hide full card numbers. Keep only the last 4 digits.

    Example: 4111 1111 1111 1234 → **-**-****-1234
    """
    if not text:
        return text

    def _replace(match: re.Match) -> str:
        # Turn the match into digits only, then keep last 4.
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 13:
            return match.group(0)
        return f"**-**-****-{digits[-4:]}"

    scrubbed = _VISA_MC_PATTERN.sub(_replace, text)
    scrubbed = _AMEX_PATTERN.sub(_replace, scrubbed)
    return scrubbed


def contains_prohibited_card_auth_data(text: str) -> bool:
    """
    Return True if the message looks like it has CVV / track / PIN data.

    Loyalty card numbers alone are fine. CVV is not.
    """
    if not text:
        return False
    lower = text.lower()
    if any(keyword in lower for keyword in _PCI_AUTH_KEYWORDS):
        return True
    return bool(_CVV_VALUE_PATTERN.search(lower))


def sanitize_user_text(text: str) -> str:
    """
    Clean what the operator typed before it enters the agent.

    Used by the API and Streamlit UI.
    """
    return mask_credit_cards(text)


def sanitize_outbound_text(text: str) -> str:
    """
    Clean text before we send email or SMS about a ticket.
    """
    return mask_credit_cards(text)
