"""
Metadata normalization for KB articles.

Maps variant product/device/category strings from the v2.2 document to
canonical values so that retrieval filters work consistently.
"""

DEVICE_NORMALIZATION: dict[str, str] = {
    "spyderwash hub": "Hub",
    "hub": "Hub",
    "spyderwash operator portal": "Portal",
    "operator portal": "Portal",
    "portal": "Portal",
    "pos terminal": "POS",
    "spyderwash pos": "POS",
    "pos": "POS",
    "legacy kiosk": "Legacy Kiosk",
    "platinum kiosk": "Platinum Kiosk",
    "card reader": "Card Reader",
    "card reader system": "Card Reader",
    "washer/dryer card reader system": "Card Reader",
    "washer/dryer card reader": "Card Reader",
    "reader": "Card Reader",
    "loyalty card": "Loyalty Card",
    "loyalty card / customer portal / operator portal": "Loyalty Card",
    "loyalty card / operator portal": "Loyalty Card",
    "customer portal": "Customer Portal",
    "mobile app": "Mobile App",
    "spyderwash mobile app": "Mobile App",
    "spyderwatch": "SpyderWatch",
    "spyderwatch / mobile app": "SpyderWatch",
    "network / power / connectivity": "Network",
    "network": "Network",
}

CATEGORY_NORMALIZATION: dict[str, str] = {
    "account/login issue": "Account/Login Issue",
    "loyalty card balance": "Loyalty Card Balance",
    "transaction lookup": "Transaction Lookup",
    "attendant management": "Attendant Management",
    "pricing change guidance": "Pricing Change",
    "spyderwatch guidance": "SpyderWatch",
    "software/portal guidance": "Software/Portal",
    "hub reboot guidance": "Hub Reboot",
    "loyalty card registration": "Loyalty Card Registration",
    "reload center": "Reload Center",
    "no connection error": "No Connection Error",
    "payment issue": "Payment Issue",
    "display issue": "Display Issue",
    "hardware malfunction": "Hardware Malfunction",
    "outage / escalation": "Outage/Escalation",
    "refund guidance": "Refund Guidance",
    "general information": "General Information",
    "card reader malfunction": "Card Reader Malfunction",
    "network / power / connectivity": "Network/Connectivity",
}


def normalize_device(raw: str) -> str:
    """Normalize a product/device string to a canonical device type."""
    if not raw:
        return "General"
    key = raw.strip().lower()
    return DEVICE_NORMALIZATION.get(key, raw.strip())


def normalize_category(raw: str) -> str:
    """Normalize a category string to a canonical category."""
    if not raw:
        return ""
    key = raw.strip().lower()
    return CATEGORY_NORMALIZATION.get(key, raw.strip())


def extract_device_type_from_product(product: str) -> str:
    """
    Infer the primary device_type from the product field.
    Used to populate the device_type routing dimension.
    """
    if not product:
        return "General"
    lower = product.lower()
    if "hub" in lower:
        return "Hub"
    if "pos" in lower:
        return "POS"
    if "legacy kiosk" in lower:
        return "Legacy Kiosk"
    if "platinum kiosk" in lower:
        return "Platinum Kiosk"
    if "kiosk" in lower:
        return "Kiosk"
    if "reader" in lower or "card reader" in lower:
        return "Card Reader"
    if "portal" in lower:
        return "Portal"
    if "loyalty" in lower:
        return "Loyalty Card"
    if "mobile" in lower or "spyderwatch" in lower:
        return "Mobile App"
    return "General"
