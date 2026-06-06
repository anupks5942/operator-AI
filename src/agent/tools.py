"""
LangChain tool definitions for the Setomatic/SpyderWash support agent.

Tools:
  - get_loyalty_balance:        Live SpyderWash production API (OperatorId=4)
  - get_transaction_history:    Live SpyderWash production API (LoggedInUserId=4, last 5 transactions)
  - check_global_system_status: Live web scrape of setomaticsystems.com/status
"""
import httpx
import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

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


# Live SpyderWash production API — OperatorId=4 is hardcoded per platform spec
_LOYALTY_BALANCE_URL = (
    "https://betasetomaticposwebapplication.spyderwash.com"
    "/api/Transactions/CheckLoyaltyCardBalance"
)
_LOYALTY_OPERATOR_ID = 4

@tool
def get_loyalty_balance(card_number: str) -> str:
    """
    Use this tool when the user asks about a loyalty card balance, current dollar
    value, points, or remaining credit for a specific SpyderWash loyalty card number.

    Calls the live SpyderWash production API to retrieve the real-time card balance.
    OperatorId is always 4 (hardcoded). The card number is passed as LoyaltyCardNo.

    Args:
        card_number: The loyalty card number extracted from the user's message
                     (e.g. "LC-5555", "5555", or any card identifier the user provides).

    Returns:
        A formatted string with the current balance (e.g. "Loyalty card LC-5555
        has a current balance of $12.50."), or a graceful error message if the
        API is unreachable, the card is not found, or the response is malformed.
    """
    try:
        response = httpx.get(
            _LOYALTY_BALANCE_URL,
            params={
                "OperatorId":    _LOYALTY_OPERATOR_ID,
                "LoyaltyCardNo": card_number,
            },
            timeout=12.0,
        )

        # Surface HTTP-level errors (4xx / 5xx) as graceful messages
        if response.status_code == 500:
            return (
                f"The SpyderWash API returned a server error (500) for card '{card_number}'. "
                "The card may not exist in this operator's system, or the backend is temporarily unavailable."
            )
        if response.status_code != 200:
            return (
                f"Unexpected API response (HTTP {response.status_code}) "
                f"while looking up loyalty card '{card_number}'. Please try again shortly."
            )

        payload = response.json()

        # Parse balance from: response['data'][0]['currentValue']
        data_array = payload.get("data")
        if not data_array or not isinstance(data_array, list) or len(data_array) == 0:
            return (
                f"No balance data found for loyalty card '{card_number}'. "
                "The card may not be registered under Operator ID 4, or the card number is incorrect."
            )

        current_value = data_array[0].get("currentValue")
        if current_value is None:
            return (
                f"The API responded successfully but 'currentValue' was missing in the data "
                f"for card '{card_number}'. The response structure may have changed — please contact support."
            )

        # Format as a currency string
        balance_str = f"${float(current_value):.2f}"
        return (
            f"Loyalty card '{card_number}' has a current balance of {balance_str}."
        )

    except httpx.TimeoutException:
        return (
            f"The loyalty balance request for card '{card_number}' timed out after 12 seconds. "
            "The SpyderWash API may be temporarily slow — please try again in a moment."
        )
    except httpx.ConnectError:
        return (
            f"Could not connect to the SpyderWash API to look up card '{card_number}'. "
            "Check network connectivity or contact Setomatic support."
        )
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return (
            f"Failed to parse the loyalty balance response for card '{card_number}': {e}. "
            "The API response format may have changed — please contact Setomatic support."
        )
    except Exception as e:
        return f"An unexpected error occurred while checking loyalty card '{card_number}': {e}"



# Live SpyderWash production transaction API
_TRANSACTION_SEARCH_URL = (
    "https://betasetomaticposwebapplication.spyderwash.com"
    "/api/Transactions/ViewAllTransactionSearch"
)
_TRANSACTION_LOGGED_IN_USER_ID = 4
_TRANSACTION_PAGE_NO   = 1
_TRANSACTION_PAGE_SIZE = 5   # Keep small to avoid context window overflow

@tool
def get_transaction_history(card_number: str) -> str:
    """
    Use this tool when the user asks to look up recent transactions, payment history,
    or wash history for a specific SpyderWash loyalty card.

    Calls the live SpyderWash production API and returns the last 5 transactions
    within the past 6 months, formatted as a human-readable summary.

    LoggedInUserId is always 4 (hardcoded). PageNo=1, PageSize=5 (hardcoded to
    prevent context window overflow). StartDate and EndDate are auto-computed.

    Args:
        card_number: The full loyalty card number extracted from the user's message
                     or conversation history (e.g. "00000212", "LC-5555").

    Returns:
        A formatted multi-line string listing each transaction's date/time,
        amount, type, and location — or a graceful error string if the API
        is unreachable, returns no data, or the response is malformed.
    """
    from datetime import datetime, timedelta, timezone

    # Auto-compute date range: last 6 months → today
    now       = datetime.now(timezone.utc)
    end_date  = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=182)).strftime("%Y-%m-%d")

    try:
        response = httpx.get(
            _TRANSACTION_SEARCH_URL,
            params={
                "LoggedInUserId": _TRANSACTION_LOGGED_IN_USER_ID,
                "LoyaltyCardNo":  card_number,
                "StartDate":      start_date,
                "EndDate":        end_date,
                "PageNo":         _TRANSACTION_PAGE_NO,
                "PageSize":       _TRANSACTION_PAGE_SIZE,
            },
            timeout=12.0,
        )

        if response.status_code == 500:
            return (
                f"The SpyderWash API returned a server error (500) for card '{card_number}'. "
                "The card may not exist under this operator, or the backend is temporarily unavailable."
            )
        if response.status_code != 200:
            return (
                f"Unexpected API response (HTTP {response.status_code}) while fetching "
                f"transactions for card '{card_number}'. Please try again shortly."
            )

        # Parse: response['data'] is the transaction array
        transactions = response.json().get("data", [])

        if not transactions:
            return (
                f"No transactions found for loyalty card '{card_number}' "
                f"between {start_date} and {end_date}. "
                "The card may have no activity in this period, or the card number is incorrect."
            )

        # Format a clean, LLM-friendly summary
        lines = [
            f"Last {len(transactions)} transaction(s) for loyalty card '{card_number}' "
            f"({start_date} → {end_date}):\n"
        ]
        for i, tx in enumerate(transactions, start=1):
            dt     = tx.get("transactionDateTime", "N/A")
            amount = tx.get("transactionAmount",   "N/A")
            t_type = tx.get("transactionType",     "N/A")
            loc    = tx.get("locationName",        "N/A")

            # Format amount as currency if numeric
            try:
                amount_str = f"${float(amount):.2f}"
            except (TypeError, ValueError):
                amount_str = str(amount)

            lines.append(
                f"  {i}. [{dt}]  {t_type}  {amount_str}  @ {loc}"
            )

        return "\n".join(lines)

    except httpx.TimeoutException:
        return (
            f"The transaction history request for card '{card_number}' timed out after 12 seconds. "
            "The SpyderWash API may be temporarily slow — please try again in a moment."
        )
    except httpx.ConnectError:
        return (
            f"Could not connect to the SpyderWash API to retrieve transactions for card '{card_number}'. "
            "Check network connectivity or contact Setomatic support."
        )
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return (
            f"Failed to parse the transaction response for card '{card_number}': {e}. "
            "The API response format may have changed — please contact Setomatic support."
        )
    except Exception as e:
        return f"An unexpected error occurred while fetching transactions for card '{card_number}': {e}"


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
