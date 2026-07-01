"""
LangChain tool definitions for the Setomatic/SpyderWash support agent.

Tools:
  - get_loyalty_balance:        Routes to SETOMATIC_BASE_URL (live production API, OperatorId=4)
  - get_transaction_history:    Routes to SETOMATIC_BASE_URL (live production API) — includes transactionDetailId for refund flow
  - check_refund_eligibility:   Routes to MOCK_BASE_URL when USE_MOCK_REFUNDS=True, else SETOMATIC_BASE_URL
  - execute_refund:             Routes to MOCK_BASE_URL when USE_MOCK_REFUNDS=True, else SETOMATIC_BASE_URL
  - check_global_system_status: Live web scrape of setomaticsystems.com/status

URL routing is controlled by src/config.py — set environment variables in .env to override defaults.
"""
# httpx replaced by requests across all tool HTTP calls for a unified error boundary interface.
import requests
import logging
import datetime
from datetime import datetime
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("setomatic.tools")

# Import centralized URL config — all base URLs are defined in src/config.py
from src.config import MOCK_BASE_URL, SETOMATIC_BASE_URL, USE_MOCK_REFUNDS

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


# ---------------------------------------------------------------------------
# Pydantic args_schema definitions
# Each schema validates the tool's input at the LangChain layer, before the
# underlying HTTP call is made — acting as a typed contract between the LLM
# output and the production API.
# ---------------------------------------------------------------------------

# Card number pattern: alphanumeric characters and hyphens only (e.g. 'LC-5555', '00000212').
_CARD_NUMBER_PATTERN = r"^[A-Za-z0-9\-]+$"

# Transaction ID pattern: same character set, accommodating IDs like 'TX-12345ABC'.
_TX_ID_PATTERN = r"^[A-Za-z0-9\-]+$"


class LoyaltyBalanceSchema(BaseModel):
    # card_number must be 4–15 chars, alphanumeric + hyphens; rejects empty or injected strings.
    card_number: str = Field(
        ...,
        min_length=4,
        max_length=15,
        pattern=_CARD_NUMBER_PATTERN,
        description="Loyalty card number (alphanumeric and hyphens, 4-15 characters).",
    )


class TransactionHistorySchema(BaseModel):
    # Shares identical card number constraints with LoyaltyBalanceSchema.
    card_number: str = Field(
        ...,
        min_length=4,
        max_length=15,
        pattern=_CARD_NUMBER_PATTERN,
        description="Loyalty card number (alphanumeric and hyphens, 4-15 characters).",
    )


class RefundEligibilitySchema(BaseModel):
    # transaction_detail_id supports alphanumeric IDs and hyphenated formats like 'TX-12345ABC'.
    transaction_detail_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=_TX_ID_PATTERN,
        description="Transaction detail ID (alphanumeric and hyphens, 1-50 characters).",
    )


class RefundExecuteSchema(BaseModel):
    # Mirrors RefundEligibilitySchema — the same ID validated in step 2 is reused in step 3.
    transaction_detail_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=_TX_ID_PATTERN,
        description="Transaction detail ID confirmed eligible in step 2 (alphanumeric and hyphens).",
    )


# ---------------------------------------------------------------------------
# Loyalty balance tool
# ---------------------------------------------------------------------------

# Loyalty balance always routes to the live production API, never the mock server
_LOYALTY_BALANCE_URL = (
    SETOMATIC_BASE_URL
    + "/api/Transactions/CheckLoyaltyCardBalance"
)
_LOYALTY_OPERATOR_ID = 4

# args_schema enforces card number length and character constraints before the API is called.
@tool(args_schema=LoyaltyBalanceSchema)
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
        params = {
            "OperatorId":    _LOYALTY_OPERATOR_ID,
            "LoyaltyCardNo": card_number,
        }
        logger.info("[get_loyalty_balance] Calling API: GET %s | Params: %s", _LOYALTY_BALANCE_URL, params)
        # Network call: requests.get with explicit connect + read timeout pair.
        response = requests.get(
            _LOYALTY_BALANCE_URL,
            params=params,
            timeout=(10.0, 12.0),
        )
        logger.info("[get_loyalty_balance] API Response [%s]: %s", response.status_code, response.text)

        # Server-side failure: instruct the LLM to tell the user the system is temporarily down.
        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "Instruct the user that the system is temporarily down."
            )

        # Business logic rejection: surface raw API text so the LLM sees the actual reason
        # (e.g. 'Card not found', 'Invalid operator') instead of a generic HTTP code.
        if 400 <= response.status_code < 500:
            return (
                f"API Error: The request was rejected. Details: {response.text}"
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

    # Network-level failure: the host is physically unreachable (DNS, TCP, or timeout).
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "Instruct the user to try again in five minutes."
        )
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return (
            f"Failed to parse the loyalty balance response for card '{card_number}': {e}. "
            "The API response format may have changed — please contact Setomatic support."
        )
    except Exception as e:
        return f"An unexpected error occurred while checking loyalty card '{card_number}': {e}"



# Transaction history always routes to the live production API, never the mock server
_TRANSACTION_SEARCH_URL = (
    SETOMATIC_BASE_URL
    + "/api/Transactions/ViewAllTransactionSearch"
)
_TRANSACTION_LOGGED_IN_USER_ID = 4
_TRANSACTION_PAGE_NO   = 1
_TRANSACTION_PAGE_SIZE = 5   # Keep small to avoid context window overflow

# ---------------------------------------------------------------------------
# Transaction history tool
# ---------------------------------------------------------------------------

# args_schema enforces identical card number constraints as the balance tool.
@tool(args_schema=TransactionHistorySchema)
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
    # This date window is temporarily locked to April 2026 to ensure the staging data renders correctly for the client demo, alongside the PageSize=5 limitation.
    start_date = '2026-04-01'
    end_date = '2026-04-30'

    try:
        # Pre-validate: confirm the card exists before fetching transactions.
        # The Setomatic ViewAllTransactionSearch API returns unscoped results for
        # invalid card numbers, so we must verify card existence first.
        logger.info("[get_transaction_history] Validating card existence: %s", card_number)
        validation_resp = requests.get(
            _LOYALTY_BALANCE_URL,
            params={"OperatorId": _LOYALTY_OPERATOR_ID, "LoyaltyCardNo": card_number},
            timeout=(10.0, 12.0),
        )
        if validation_resp.status_code == 200:
            validation_data = validation_resp.json().get("data", [])
            if not validation_data:
                return (
                    f"Loyalty card '{card_number}' was not found in the system. "
                    "Cannot retrieve transactions for an unregistered card. "
                    "Please verify the card number and try again."
                )

        params = {
            'LoggedInUserId': 4,
            'IsFundAmountUsed': 'true',
            'StartDate': start_date,
            'EndDate': end_date,
            'LoyaltyCardNo': card_number,
            'PageNo': 1,
            'PageSize': 5
        }
        logger.info("[get_transaction_history] Calling API: GET %s | Params: %s", _TRANSACTION_SEARCH_URL, params)
        response = requests.get(
            _TRANSACTION_SEARCH_URL,
            params=params,
            timeout=(10.0, 12.0),
        )
        logger.info("[get_transaction_history] API Response [%s]: %s", response.status_code, response.text)

        # Server-side failure: instruct the LLM to tell the user the system is temporarily down.
        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "Instruct the user that the system is temporarily down."
            )

        # Business logic rejection: surface raw API text so the LLM sees the actual reason.
        if 400 <= response.status_code < 500:
            return (
                f"API Error: The request was rejected. Details: {response.text}"
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
            f"({start_date} -> {end_date}):\n"
        ]
        for i, tx in enumerate(transactions, start=1):
            tx_id  = tx.get("transactionDetailId", "N/A")  # required for refund flow
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
                f"  {i}. [ID:{tx_id}]  [{dt}]  {t_type}  {amount_str}  @ {loc}"
            )

        return "\n".join(lines)

    # Network-level failure: the host is physically unreachable (DNS, TCP, or timeout).
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "Instruct the user to try again in five minutes."
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
            logger.info("[check_global_system_status] Warming up session at https://setomaticsystems.com/")
            session.get("https://setomaticsystems.com/", timeout=8)
            # Now fetch the actual status page
            logger.info("[check_global_system_status] Fetching https://setomaticsystems.com/status")
            resp = session.get("https://setomaticsystems.com/status", timeout=10)
            logger.info("[check_global_system_status] Setomatic status page Response [%s]", resp.status_code)
        except Exception as e:
            logger.error("[check_global_system_status] Failed to fetch setomatic status: %s", e)
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
            logger.info("[check_global_system_status] Fetching fallback: https://www.cantaloupe.com/status")
            resp = requests.get("https://www.cantaloupe.com/status", headers=headers, timeout=10)
            logger.info("[check_global_system_status] Cantaloupe status page Response [%s]", resp.status_code)
        except Exception as e:
            logger.error("[check_global_system_status] Failed to fetch cantaloupe status: %s", e)
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


# Refund tools route to MOCK_BASE_URL when USE_MOCK_REFUNDS is True, else fall back to production
_REFUND_BASE = MOCK_BASE_URL if USE_MOCK_REFUNDS else SETOMATIC_BASE_URL
_REFUND_OPERATOR_ID = 4


# ---------------------------------------------------------------------------
# Refund tools
# ---------------------------------------------------------------------------

# args_schema rejects transaction IDs that contain disallowed characters or exceed length bounds.
@tool(args_schema=RefundEligibilitySchema)
def check_refund_eligibility(transaction_detail_id: str) -> str:
    """
    Use this tool AFTER calling get_transaction_history to check whether a specific
    transaction is eligible for a refund.

    MUST be called as step 2 of the refund workflow:
      1. get_transaction_history  → obtain transactionDetailId
      2. check_refund_eligibility → verify the 30-day window (this tool)
      3. execute_refund           → ONLY if isEligible is true

    OperatorId is always 4 (hardcoded).

    Args:
        transaction_detail_id: The transactionDetailId string from the transaction
                               history result (e.g. "12345").

    Returns:
        A plain-text string indicating whether the transaction is eligible for a
        refund and the reason provided by the API, or a graceful error string.
    """
    try:
        url = f"{_REFUND_BASE}/api/Transactions/RefundEligibility"
        params = {
            "transactionDetailId": transaction_detail_id,
            "OperatorId":          _REFUND_OPERATOR_ID,
        }
        logger.info("[check_refund_eligibility] Calling API: GET %s | Params: %s", url, params)
        # Network call: requests.get with explicit connect + read timeout pair.
        response = requests.get(
            url,
            params=params,
            timeout=(8.0, 10.0),
        )
        logger.info("[check_refund_eligibility] API Response [%s]: %s", response.status_code, response.text)

        # Server-side failure: instruct the LLM to tell the user the system is temporarily down.
        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "Instruct the user that the system is temporarily down."
            )

        # Business logic rejection: surface raw API text so the LLM sees the actual reason.
        if 400 <= response.status_code < 500:
            return (
                f"API Error: The request was rejected. Details: {response.text}"
            )

        data        = response.json().get("data", {})
        is_eligible = data.get("isEligible")
        reason      = data.get("reason", "No reason provided.")

        if is_eligible is None:
            return (
                f"Refund eligibility check for transaction '{transaction_detail_id}' returned "
                "an unexpected response structure. Please contact Setomatic support."
            )

        if is_eligible:
            return (
                f"Transaction ID '{transaction_detail_id}' IS eligible for a refund. "
                f"Reason: {reason}. You may now proceed to process the refund."
            )
        else:
            return (
                f"Transaction ID '{transaction_detail_id}' is NOT eligible for a refund. "
                f"Reason: {reason}. No refund can be issued."
            )

    # Network-level failure: the host is physically unreachable (DNS, TCP, or timeout).
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "Instruct the user to try again in five minutes."
        )
    except (KeyError, ValueError, TypeError) as e:
        return f"Failed to parse refund eligibility response for transaction '{transaction_detail_id}': {e}."
    except Exception as e:
        return f"Unexpected error during refund eligibility check for '{transaction_detail_id}': {e}"


# args_schema mirrors RefundEligibilitySchema — the same validated ID flows from step 2 into step 3.
@tool(args_schema=RefundExecuteSchema)
def execute_refund(transaction_detail_id: str) -> str:
    """
    Use this tool ONLY after check_refund_eligibility confirms isEligible=True.
    This is step 3 of the mandatory refund workflow:

      1. get_transaction_history  → obtain transactionDetailId
      2. check_refund_eligibility → must return isEligible=True
      3. execute_refund           → this tool — processes the refund

    WARNING: Do NOT call this tool if check_refund_eligibility returned
    isEligible=False. The refund will be rejected.

    OperatorId is always 4 (hardcoded).

    Args:
        transaction_detail_id: The transactionDetailId string confirmed as
                               eligible in step 2 (e.g. "12345").

    Returns:
        A confirmation string with the refund receipt number on success,
        or a graceful error string if the API fails.
    """
    try:
        url = f"{_REFUND_BASE}/api/Transactions/RefundProcessing"
        params = {
            "transactionDetailId": transaction_detail_id,
            "OperatorId":          _REFUND_OPERATOR_ID,
        }
        logger.info("[execute_refund] Calling API: GET %s | Params: %s", url, params)
        # Network call: requests.get with explicit connect + read timeout pair.
        response = requests.get(
            url,
            params=params,
            timeout=(8.0, 10.0),
        )
        logger.info("[execute_refund] API Response [%s]: %s", response.status_code, response.text)

        # Server-side failure: instruct the LLM to tell the user the system is temporarily down.
        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "Instruct the user that the system is temporarily down."
            )

        # Business logic rejection: surface raw API text so the LLM sees the actual reason.
        if 400 <= response.status_code < 500:
            return (
                f"API Error: The request was rejected. Details: {response.text}"
            )

        payload = response.json()
        message = payload.get("message", "Refund processed.")
        receipt = payload.get("data", {}).get("refundReceipt", "N/A")

        return (
            f"Refund successfully processed for transaction ID '{transaction_detail_id}'. "
            f"{message} Receipt number: {receipt}."
        )

    # Network-level failure: the host is physically unreachable (DNS, TCP, or timeout).
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "Instruct the user to try again in five minutes."
        )
    except (KeyError, ValueError, TypeError) as e:
        return f"Failed to parse refund processing response for transaction '{transaction_detail_id}': {e}."
    except Exception as e:
        return f"Unexpected error during refund processing for '{transaction_detail_id}': {e}"


# Exported list for binding to LLM
SETOMATIC_TOOLS = [
    get_loyalty_balance,
    get_transaction_history,
    check_refund_eligibility,
    execute_refund,
    check_global_system_status,
]
