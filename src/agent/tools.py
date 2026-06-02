"""
LangChain tool definitions that call the local mock API server and live web endpoints.
The mock API server must be running at http://localhost:8001 before loyalty/transaction tools are invoked.
"""
import httpx
import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

BASE_URL = "http://localhost:8001"

# Chrome-mimicking headers — Accept-Encoding intentionally omitted so requests
# receives plain HTML (not brotli/gzip binary that requests can't decompress natively)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

@tool
def get_loyalty_balance(card_number: str) -> dict:
    """
    Use this tool when the user asks about a loyalty card balance, current points,
    or loyalty tier for a specific card number.

    Args:
        card_number: The full loyalty card number provided by the user (e.g. "LC-12345678").

    Returns:
        A dictionary containing:
        - status: "success" or "error"
        - card_number: the card queried
        - balance_usd: current dollar balance on the card
        - loyalty_tier: "Gold" or "Standard"
        - points: accumulated loyalty points
    """
    try:
        response = httpx.post(
            f"{BASE_URL}/api/v1/loyalty/balance",
            json={"card_number": card_number},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.ConnectError:
        return {"status": "error", "detail": "Mock API server is not running. Start it with: uv run uvicorn src.api.mock_server:mock_app --port 8001"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@tool
def get_transaction_history(card_ending: str) -> dict:
    """
    Use this tool when the user asks to look up recent transactions, payment history,
    or wash history for a loyalty card identified by its last few digits.

    Args:
        card_ending: The last 4 digits of the loyalty card (e.g. "4521").

    Returns:
        A dictionary containing:
        - status: "success" or "error"
        - card_ending: the card suffix queried
        - transaction_count: number of transactions returned
        - transactions: list of transaction records, each with tx_id, date, type, amount_usd, machine_id
    """
    try:
        response = httpx.post(
            f"{BASE_URL}/api/v1/transactions/lookup",
            json={"card_ending": card_ending},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.ConnectError:
        return {"status": "error", "detail": "Mock API server is not running. Start it with: uv run uvicorn src.api.mock_server:mock_app --port 8001"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@tool
def check_global_system_status() -> str:
    """
    Use this tool when the user asks whether the SpyderWash / Setomatic global
    system is down, experiencing an outage, or has degraded service.

    Fetches the live status page at https://setomaticsystems.com/status and parses
    the current operational status. Falls back to https://www.cantaloupe.com/status
    if the primary page is WAF-blocked. Takes NO arguments.

    Returns:
        A plain-text string with the current system status, details, and date.
        If the Cantaloupe fallback is used, incidents older than 7 days are clearly
        labelled as HISTORICAL/RESOLVED so the LLM does not misreport them as current.
    """
    import re
    from datetime import datetime, timezone

    # ── Helper: parse MM.DD.YY date strings ──────────────────────────────────
    def _parse_incident_date(date_str: str):
        """Return a datetime from 'MM.DD.YY' format, or None if unparseable."""
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", date_str)
        if not m:
            return None
        try:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(2000 + year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    # ── Strategy 1: setomaticsystems.com via requests.Session ────────────────
    def _try_setomatic() -> str | None:
        """
        Use a Session object to warm up cookies/headers before fetching the status page.
        This improves WAF bypass success vs a cold single GET request.
        Parses the 'STATUS:' heading specific to the Setomatic page structure.
        """
        session = requests.Session()
        session.headers.update(_BROWSER_HEADERS)
        session.headers.update({
            "Origin":  "https://setomaticsystems.com",
            "Referer": "https://setomaticsystems.com/",
        })
        try:
            # Warm-up request to the homepage first (establishes session context)
            session.get("https://setomaticsystems.com/", timeout=8)
            # Now fetch the actual status page
            resp = session.get("https://setomaticsystems.com/status", timeout=10)
        except Exception:
            return None

        if resp.status_code != 200:
            return None

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            visible = soup.get_text(separator=" | ", strip=True)

            # Setomatic page structure: h2 with "STATUS: <value>"
            # e.g. "STATUS: No Issue" or "STATUS: Degraded"
            m_status = re.search(r"(STATUS:\s*[^\|]{2,60})", visible, re.IGNORECASE)
            if not m_status:
                return None

            status_line = m_status.group(1).strip()

            # Grab the descriptive paragraph that follows
            m_desc = re.search(
                re.escape(status_line) + r"\s*\|?\s*(.{20,600}?)(?:\||\Z)",
                visible, re.IGNORECASE | re.DOTALL,
            )
            description = m_desc.group(1).strip()[:350] if m_desc else ""

            result = f"[Setomatic Systems] {status_line}"
            if description:
                result += f" | Details: {description}"
            return result

        except Exception:
            return None

    # ── Strategy 2: cantaloupe.com/status (fallback) ─────────────────────────
    def _try_cantaloupe() -> str | None:
        """
        Fetch Cantaloupe's status page and extract the most recent incident.
        Critically: check the incident date. If it is older than 7 days, mark it
        as HISTORICAL so the LLM does not present a resolved past incident as
        the current system status.
        """
        headers = {**_BROWSER_HEADERS, "Referer": "https://www.cantaloupe.com/", "DNT": "1"}
        try:
            resp = requests.get("https://www.cantaloupe.com/status", headers=headers, timeout=10)
        except Exception:
            return None

        if resp.status_code != 200:
            return None

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            visible = soup.get_text(separator=" | ", strip=True)

            # Cantaloupe structure: "System Status | MM.DD.YY | HH:MMam TZ | Event | Update: | Details"
            m = re.search(
                r"System Status\s*\|?\s*"
                r"(\d{2}\.\d{2}\.\d{2}[^|]*)"                   # date
                r"\|?\s*"
                r"(?:(\d{1,2}:\d{2}(?:am|pm)[^|]*)\|?\s*)?"     # optional time
                r"([^|]{3,120})"                                  # event title
                r"(?:\s*\|?\s*Update:\s*\|?\s*(.{10,500}))?",    # optional update body
                visible,
                re.IGNORECASE | re.DOTALL,
            )

            if not m:
                return None

            date_raw   = (m.group(1) or "").strip(" |")
            time_raw   = (m.group(2) or "").strip(" |")
            event_raw  = (m.group(3) or "").strip(" |")
            update_raw = (m.group(4) or "").strip(" |")[:300]
            date_str   = f"{date_raw} {time_raw}".strip() if time_raw else date_raw

            # ── Staleness check ──────────────────────────────────────────────
            incident_dt = _parse_incident_date(date_raw)
            now_utc     = datetime.now(timezone.utc)
            is_stale    = incident_dt and (now_utc - incident_dt).days > 7

            if is_stale:
                # This is a historical/resolved incident — label it clearly
                prefix = (
                    f"[Cantaloupe (backup)] HISTORICAL INCIDENT ({date_str}) — "
                    f"This incident occurred {(now_utc - incident_dt).days} days ago and "
                    f"is likely resolved. DO NOT report this as the current system status. "
                    f"Event: {event_raw}"
                )
                if update_raw:
                    prefix += f" | Last update: {update_raw}"
                prefix += " | NOTE: Check https://setomaticsystems.com/status for current status."
                return prefix

            # Recent incident — report it as current
            parts = [f"[Cantaloupe (backup)] System Status", f"Event: {event_raw}"]
            if date_str:
                parts.append(f"Date: {date_str}")
            if update_raw:
                parts.append(f"Details: {update_raw}")
            return " | ".join(parts)

        except Exception:
            return None

    # ── Execute cascade ───────────────────────────────────────────────────────
    result = _try_setomatic()
    if result:
        return result

    result = _try_cantaloupe()
    if result:
        return result

    return (
        "SYSTEM STATUS CHECK FAILED: Could not reach setomaticsystems.com/status "
        "(WAF-blocked) or cantaloupe.com/status. "
        "Advise the user to check https://setomaticsystems.com/status directly in a browser."
    )


# Exported list for binding to LLM
SETOMATIC_TOOLS = [get_loyalty_balance, get_transaction_history, check_global_system_status]
