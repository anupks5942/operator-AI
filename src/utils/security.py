import re

def mask_credit_cards(text: str) -> str:
    # Strict regex pattern for standard 16-digit credit cards (Visa, Mastercard, etc.)
    visa_mc_pattern = r'\b(?:\d{4}[ -]?){3}\d{4}\b'
    # Strict regex pattern for standard 15-digit credit cards (American Express)
    amex_pattern = r'\b3[47]\d{2}[ -]?\d{6}[ -]?\d{5}\b'

    def replace_match(match: re.Match) -> str:
        # Strip spaces and hyphens to extract only digits
        digits = re.sub(r'\D', '', match.group(0))
        # Mask the credit card number, retaining only the last 4 digits
        return f"**-**-****-{digits[-4:]}"

    # Mask any detected standard credit card numbers to maintain PCI-DSS compliance
    scrubbed = re.sub(visa_mc_pattern, replace_match, text)
    scrubbed = re.sub(amex_pattern, replace_match, scrubbed)
    return scrubbed
