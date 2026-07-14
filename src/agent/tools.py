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
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("setomatic.tools")

# Import centralized URL config — all base URLs are defined in src/config.py
from src.config import MOCK_BASE_URL, SETOMATIC_BASE_URL, USE_MOCK_REFUNDS

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,hi;q=0.7",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
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
    count: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of recent transactions to retrieve (1-20, default 5).",
    )
    include_refunds: bool = Field(
        default=False,
        description="Set to true ONLY when the user explicitly asks for refunded transactions or refund history. Default false returns normal (non-refunded) transactions.",
    )
    start_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "Start date for the transaction search window (YYYY-MM-DD format). "
            "Use when the operator specifies a date range. If omitted, defaults to 6 months ago."
        ),
    )
    end_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "End date for the transaction search window (YYYY-MM-DD format). "
            "Use when the operator specifies a date range. If omitted, defaults to today."
        ),
    )
    page_no: int = Field(
        default=1,
        ge=1,
        description="Page number for pagination. Increment when operator asks 'show more'.",
    )

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_date_parseable(cls, v):
        if v is None:
            return v
        from datetime import date as date_type
        try:
            date_type.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format '{v}'. Must be YYYY-MM-DD.")
        return v


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


class KioskPurchasesSchema(BaseModel):
    start_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Start date for the search window (YYYY-MM-DD). Required.",
    )
    end_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="End date for the search window (YYYY-MM-DD). Required.",
    )
    location_name: str | None = Field(
        default=None,
        description="Filter by location name. Optional.",
    )
    imei: str | None = Field(
        default=None,
        description="Filter by kiosk IMEI/device ID. Optional.",
    )
    page_size: int = Field(default=5, ge=1, le=100, description="Results per page (default 5).")
    page_no: int = Field(default=1, ge=1, description="Page number for pagination. Increment for 'show more'.")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_date(cls, v):
        if v is None:
            return v
        from datetime import date as date_type
        try:
            date_type.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format '{v}'. Must be YYYY-MM-DD.")
        return v


class KioskRechargesSchema(BaseModel):
    start_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Start date for the search window (YYYY-MM-DD). Required.",
    )
    end_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="End date for the search window (YYYY-MM-DD). Required.",
    )
    location_name: str | None = Field(
        default=None,
        description="Filter by location name. Optional.",
    )
    imei: str | None = Field(
        default=None,
        description="Filter by kiosk IMEI/device ID. Optional.",
    )
    page_size: int = Field(default=5, ge=1, le=100, description="Results per page (default 5).")
    page_no: int = Field(default=1, ge=1, description="Page number for pagination. Increment for 'show more'.")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_date(cls, v):
        if v is None:
            return v
        from datetime import date as date_type
        try:
            date_type.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format '{v}'. Must be YYYY-MM-DD.")
        return v


class POSTransactionsSchema(BaseModel):
    start_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Start date (YYYY-MM-DD). Required.",
    )
    end_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="End date (YYYY-MM-DD). Required.",
    )
    card_code: int = Field(
        default=17,
        description="Payment type filter: 17=Loyalty Card (default), 19=Credit Card, 20=Cash.",
    )
    order_type: int = Field(
        default=1,
        description="Order type: 1=All (default), 2=Sale only, 3=WDF and PUD.",
    )
    account_type: int = Field(
        default=1,
        description="Customer type: 1=All (default), 2=Commercial only, 3=Non-commercial only.",
    )
    card_no: str | None = Field(
        default=None,
        description="Filter by specific card number. Optional.",
    )
    location_id: int | None = Field(
        default=None,
        description="Filter by location ID. Optional.",
    )
    pos_id: str | None = Field(
        default=None,
        description="Filter by POS terminal ID. Optional.",
    )
    page_size: int = Field(default=5, ge=1, le=100, description="Results per page (default 5).")
    page_no: int = Field(default=1, ge=1, description="Page number for pagination. Increment for 'show more'.")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_date(cls, v):
        if v is None:
            return v
        from datetime import date as date_type
        try:
            date_type.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format '{v}'. Must be YYYY-MM-DD.")
        return v


class RemoteDeviceCommandSchema(BaseModel):
    device_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Target device ID/IMEI to send the command to.",
    )
    command: str = Field(
        ...,
        description="Command to execute: 'Dispense' (dispense a loyalty card) or 'Reboot' (restart device).",
    )
    amount: float = Field(
        default=0,
        ge=0,
        description="Dollar amount for card dispense (must be > 0 for Dispense, 0 for Reboot).",
    )

    @field_validator("command", mode="before")
    @classmethod
    def _validate_command(cls, v):
        normalized = v.strip().capitalize()
        if normalized not in ("Dispense", "Reboot"):
            raise ValueError(f"Invalid command '{v}'. Must be 'Dispense' or 'Reboot'.")
        return normalized


def _normalize_card_number(card_number: str) -> str:
    """Strip common prefixes (LC-, lc-, LC, lc) that operators prepend to card numbers."""
    import re
    stripped = re.sub(r'^(?:lc[-\s]*)', '', card_number.strip(), flags=re.IGNORECASE)
    return stripped.strip() or card_number


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
        card_number = _normalize_card_number(card_number)
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
def get_transaction_history(
    card_number: str,
    count: int = 5,
    include_refunds: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
    page_no: int = 1,
) -> str:
    """
    Use this tool when the user asks to look up recent transactions, payment history,
    refund history, or wash history for a specific SpyderWash loyalty card.

    Calls the live SpyderWash production API and returns recent transactions
    formatted as a human-readable summary.

    LoggedInUserId is always 4 (hardcoded).

    Args:
        card_number: The full loyalty card number extracted from the user's message
                     or conversation history (e.g. "00000212", "LC-5555").
        count: Number of transactions to retrieve (1-20, default 5). Use the number
               the user explicitly requested, or default to 5.
        include_refunds: Set to true when the user asks specifically for refunded
                         transactions or refund history. Default false shows normal transactions.
        start_date: Start of the search window in YYYY-MM-DD format. Defaults to
                    6 months before end_date when not provided by the operator.
        end_date: End of the search window in YYYY-MM-DD format. Defaults to today
                  when not provided by the operator.

    Returns:
        A formatted multi-line string listing each transaction's date/time,
        amount, type, and location — or a graceful error string if the API
        is unreachable, returns no data, or the response is malformed.
    """
    from datetime import date, timedelta

    card_number = _normalize_card_number(card_number)

    # Resolve date window: operator-provided dates take priority, otherwise rolling 6-month default.
    if end_date:
        try:
            resolved_end = date.fromisoformat(end_date)
        except ValueError:
            resolved_end = date.today()
    else:
        resolved_end = date.today()

    if start_date:
        try:
            resolved_start = date.fromisoformat(start_date)
        except ValueError:
            resolved_start = resolved_end - timedelta(days=180)
    else:
        resolved_start = resolved_end - timedelta(days=180)

    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start

    start_date = resolved_start.isoformat()
    end_date = resolved_end.isoformat()

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

        page_size = max(1, min(count, 20))
        params = {
            'LoggedInUserId': 4,
            'IsFundAmountUsed': 'true',
            'StartDate': start_date,
            'EndDate': end_date,
            'LoyaltyCardNo': card_number,
            'PageNo': page_no,
            'PageSize': page_size,
            'isRefund': 'true' if include_refunds else 'false',
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

        # Sort by date descending (most recent first) — API does not guarantee order.
        transactions.sort(
            key=lambda tx: tx.get("transactionDateTime", ""),
            reverse=True,
        )

        if not transactions:
            tx_type = "refunded transactions" if include_refunds else "transactions"
            return (
                f"No {tx_type} found for loyalty card '{card_number}' "
                f"between {start_date} and {end_date}. "
                f"The card may have no {'refund' if include_refunds else ''} activity in this period."
            )

        total_records = response.json().get("totalRecords") or response.json().get("totalrecords") or len(transactions)

        tx_label = "refunded transaction(s)" if include_refunds else "transaction(s)"
        lines = [
            f"**{tx_label.capitalize()}** for loyalty card '{card_number}' "
            f"({start_date} to {end_date}):\n"
        ]
        tx_ids = []
        for i, tx in enumerate(transactions, start=1):
            tx_id  = tx.get("transactionDetailId", "N/A")
            dt     = tx.get("transactionDateTime", "N/A")
            amount = tx.get("transactionAmount",   "N/A")
            t_type = tx.get("transactionType",     "N/A")
            loc    = tx.get("locationName",        "N/A")

            try:
                amount_str = f"${float(amount):.2f}"
            except (TypeError, ValueError):
                amount_str = str(amount)

            lines.append(
                f"  {i}. [{dt}]  {t_type}  {amount_str}  @ {loc}"
            )
            tx_ids.append(str(tx_id))

        shown = len(transactions)
        remaining = int(total_records) - (page_no * page_size) if int(total_records) > page_no * page_size else 0
        if remaining > 0:
            lines.append(
                f"\nShowing {shown} of {total_records} records. "
                f"{remaining} more records are available. "
                f"Say \"show more\" to view the next {page_size} records."
            )
        else:
            lines.append(f"\nShowing all {total_records} records.")

        lines.append("\n(Internal — transaction IDs for refund flow: " + ", ".join(tx_ids) + ")")

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
    the current operational status. Takes NO arguments.

    Returns:
        A plain-text string with the current system status and details.
    """
    import re

    _STATUS_URL = "https://setomaticsystems.com/status/"

    # ── Strategy 1: cloudscraper (handles Cloudflare JS challenges) ───────────
    def _try_cloudscraper() -> str | None:
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            logger.info("[check_global_system_status] Fetching %s via cloudscraper", _STATUS_URL)
            resp = scraper.get(_STATUS_URL, timeout=15)
            logger.info("[check_global_system_status] cloudscraper Response [%s]", resp.status_code)
            if resp.status_code == 200:
                return resp.text
        except ImportError:
            logger.warning("[check_global_system_status] cloudscraper not installed, skipping")
        except Exception as e:
            logger.error("[check_global_system_status] cloudscraper failed: %s", e)
        return None

    # ── Strategy 2: requests.Session with full browser headers ────────────────
    def _try_requests_session() -> str | None:
        session = requests.Session()
        session.headers.update(_BROWSER_HEADERS)
        try:
            logger.info("[check_global_system_status] Warming up session at https://setomaticsystems.com/")
            session.get("https://setomaticsystems.com/", timeout=8)
            logger.info("[check_global_system_status] Fetching %s", _STATUS_URL)
            resp = session.get(_STATUS_URL, timeout=10)
            logger.info("[check_global_system_status] Setomatic status page Response [%s]", resp.status_code)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logger.error("[check_global_system_status] Failed to fetch setomatic status: %s", e)
        return None

    # ── Parse the HTML response ───────────────────────────────────────────────
    def _parse_status_html(html_text: str) -> str | None:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            visible = soup.get_text(separator=" | ", strip=True)

            m_status = re.search(r"(STATUS:\s*[^\|]{2,60})", visible, re.IGNORECASE)
            if not m_status:
                return None

            status_line = m_status.group(1).strip()

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

    # ── Execute cascade ─────────────────────────────────────────────────────────
    html_text = _try_cloudscraper() or _try_requests_session()
    if html_text:
        parsed = _parse_status_html(html_text)
        if parsed:
            logger.info("[check_global_system_status] Parsed result: %s", parsed)
            return parsed
        logger.warning("[check_global_system_status] Got 200 but failed to parse STATUS from HTML")

    return (
        "SYSTEM STATUS CHECK FAILED: Could not reach setomaticsystems.com/status. "
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


# ---------------------------------------------------------------------------
# Kiosk Purchases tool
# ---------------------------------------------------------------------------

_KIOSK_PURCHASES_URL = (
    SETOMATIC_BASE_URL
    + "/api/Kiosk/GetKioskPurchasedLoyaltyCarddetails"
)
_KIOSK_OPERATOR_ID = 4


@tool(args_schema=KioskPurchasesSchema)
def get_kiosk_purchases(
    start_date: str,
    end_date: str,
    location_name: str | None = None,
    imei: str | None = None,
    page_size: int = 5,
    page_no: int = 1,
) -> str:
    """
    Use this tool when the operator asks about loyalty cards PURCHASED (sold/dispensed)
    at a kiosk within a date range.

    Returns details of loyalty cards that were purchased through kiosk machines,
    including card numbers, amounts, timestamps, and kiosk/location info.

    Args:
        start_date: Start of the search window (YYYY-MM-DD).
        end_date: End of the search window (YYYY-MM-DD).
        location_name: Optional location filter.
        imei: Optional kiosk IMEI filter.
        page_size: Number of results per page (1-100, default 20).
    """
    try:
        body = {
            "UserId": _KIOSK_OPERATOR_ID,
            "startFrom": start_date,
            "ToEnd": end_date,
            "locationName": location_name,
            "IMEI": imei,
            "PageNo": 1,
            "PageSize": page_size,
        }
        logger.info("[get_kiosk_purchases] POST %s | Body: %s", _KIOSK_PURCHASES_URL, body)

        response = requests.get(
            _KIOSK_PURCHASES_URL,
            params={"UserId": _KIOSK_OPERATOR_ID, "startFrom": start_date, "ToEnd": end_date},
            json=body,
            timeout=(10.0, 15.0),
        )
        logger.info("[get_kiosk_purchases] Response [%s]: %s", response.status_code, response.text[:500])

        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "Instruct the user that the system is temporarily down."
            )

        if 400 <= response.status_code < 500:
            return f"API Error: The request was rejected. Details: {response.text}"

        payload = response.json()
        data = payload.get("data") or payload if isinstance(payload, list) else payload.get("data")

        if not data:
            return (
                f"No kiosk purchase records found between {start_date} and {end_date}. "
                "The date range may be too narrow or no purchases occurred in this period."
            )

        records = data if isinstance(data, list) else [data]
        records.sort(
            key=lambda r: r.get("transactionDate") or r.get("purchaseDate") or "",
            reverse=True,
        )

        total = len(records)
        start_idx = (page_no - 1) * page_size
        page_records = records[start_idx : start_idx + page_size]

        if not page_records:
            return f"No more kiosk purchase records to show (page {page_no} is empty)."

        shown = len(page_records)
        lines = [f"**Kiosk Loyalty Card Purchases** ({start_date} to {end_date}):\n"]
        for i, rec in enumerate(page_records, start=start_idx + 1):
            card_no = rec.get("loyaltyCardNo") or rec.get("cardNo") or "N/A"
            amount_raw = rec.get("transactionAmount") if rec.get("transactionAmount") is not None else rec.get("amount") if rec.get("amount") is not None else rec.get("cardValue")
            amount = f"${float(amount_raw):.2f}" if amount_raw is not None else "N/A"
            bonus_raw = rec.get("bonusAmount")
            bonus = f" (bonus: ${float(bonus_raw):.2f})" if bonus_raw and float(bonus_raw) > 0 else ""
            date_raw = rec.get("transactionDate") or rec.get("purchaseDate") or ""
            date_val = date_raw.split("T")[0] if "T" in date_raw else (date_raw or "N/A")
            location = rec.get("locationName") or rec.get("location") or "N/A"
            device = rec.get("reloadCenterHubMacId") or rec.get("imei") or rec.get("deviceId") or "N/A"
            payment = rec.get("cardName") or ""
            payment_label = f" | Paid via: {payment}" if payment else ""
            lines.append(
                f"{i}. Card: {card_no} | Amount: {amount}{bonus} | Date: {date_val} | "
                f"Location: {location} | Device: {device}{payment_label}"
            )

        remaining = total - (start_idx + shown)
        if remaining > 0:
            lines.append(
                f"\nShowing {shown} of {total} records. "
                f"{remaining} more records are available. "
                f"Say \"show more\" to view the next {page_size} records."
            )
        else:
            lines.append(f"\nShowing all {total} records.")

        return "\n".join(lines)

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "Instruct the user to try again in five minutes."
        )
    except (KeyError, ValueError, TypeError) as e:
        return f"Failed to parse kiosk purchases response: {e}"
    except Exception as e:
        return f"Unexpected error fetching kiosk purchases: {e}"


# ---------------------------------------------------------------------------
# Kiosk Recharges tool
# ---------------------------------------------------------------------------

_KIOSK_RECHARGES_URL = (
    SETOMATIC_BASE_URL
    + "/api/Kiosk/GetKioskLoyaltyCardRechargedetails"
)


@tool(args_schema=KioskRechargesSchema)
def get_kiosk_recharges(
    start_date: str,
    end_date: str,
    location_name: str | None = None,
    imei: str | None = None,
    page_size: int = 5,
    page_no: int = 1,
) -> str:
    """
    Use this tool when the operator asks about loyalty card RECHARGES (top-ups)
    performed at a kiosk within a date range.

    Returns details of loyalty cards that were recharged/topped-up through kiosk
    machines, including card numbers, recharge amounts, timestamps, and kiosk info.

    Args:
        start_date: Start of the search window (YYYY-MM-DD).
        end_date: End of the search window (YYYY-MM-DD).
        location_name: Optional location filter.
        imei: Optional kiosk IMEI filter.
        page_size: Number of results per page (1-100, default 20).
    """
    try:
        body = {
            "UserId": _KIOSK_OPERATOR_ID,
            "startFrom": start_date,
            "ToEnd": end_date,
            "locationName": location_name,
            "IMEI": imei,
            "PageNo": 1,
            "PageSize": page_size,
        }
        logger.info("[get_kiosk_recharges] GET %s | Body: %s", _KIOSK_RECHARGES_URL, body)

        response = requests.get(
            _KIOSK_RECHARGES_URL,
            params={"UserId": _KIOSK_OPERATOR_ID, "startFrom": start_date, "ToEnd": end_date},
            json=body,
            timeout=(10.0, 15.0),
        )
        logger.info("[get_kiosk_recharges] Response [%s]: %s", response.status_code, response.text[:500])

        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "Instruct the user that the system is temporarily down."
            )

        if 400 <= response.status_code < 500:
            return f"API Error: The request was rejected. Details: {response.text}"

        payload = response.json()
        data = payload.get("data") or payload if isinstance(payload, list) else payload.get("data")

        if not data:
            return (
                f"No kiosk recharge records found between {start_date} and {end_date}. "
                "The date range may be too narrow or no recharges occurred in this period."
            )

        records = data if isinstance(data, list) else [data]
        records.sort(
            key=lambda r: r.get("transactionDate") or r.get("rechargeDate") or "",
            reverse=True,
        )

        total = len(records)
        start_idx = (page_no - 1) * page_size
        page_records = records[start_idx : start_idx + page_size]

        if not page_records:
            return f"No more kiosk recharge records to show (page {page_no} is empty)."

        shown = len(page_records)
        lines = [f"**Kiosk Loyalty Card Recharges** ({start_date} to {end_date}):\n"]
        for i, rec in enumerate(page_records, start=start_idx + 1):
            card_no = rec.get("loyaltyCardNo") or rec.get("cardNo") or "N/A"
            amount_raw = rec.get("transactionAmount") if rec.get("transactionAmount") is not None else rec.get("amount") if rec.get("amount") is not None else rec.get("rechargeAmount")
            amount = f"${float(amount_raw):.2f}" if amount_raw is not None else "N/A"
            bonus_raw = rec.get("bonusAmount")
            bonus = f" (bonus: ${float(bonus_raw):.2f})" if bonus_raw and float(bonus_raw) > 0 else ""
            date_raw = rec.get("transactionDate") or rec.get("rechargeDate") or ""
            date_val = date_raw.split("T")[0] if "T" in date_raw else (date_raw or "N/A")
            location = rec.get("locationName") or rec.get("location") or "N/A"
            device = rec.get("reloadCenterHubMacId") or rec.get("imei") or rec.get("deviceId") or "N/A"
            payment = rec.get("cardName") or ""
            payment_label = f" | Paid via: {payment}" if payment else ""
            lines.append(
                f"{i}. Card: {card_no} | Amount: {amount}{bonus} | Date: {date_val} | "
                f"Location: {location} | Device: {device}{payment_label}"
            )

        remaining = total - (start_idx + shown)
        if remaining > 0:
            lines.append(
                f"\nShowing {shown} of {total} records. "
                f"{remaining} more records are available. "
                f"Say \"show more\" to view the next {page_size} records."
            )
        else:
            lines.append(f"\nShowing all {total} records.")

        return "\n".join(lines)

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "Instruct the user to try again in five minutes."
        )
    except (KeyError, ValueError, TypeError) as e:
        return f"Failed to parse kiosk recharges response: {e}"
    except Exception as e:
        return f"Unexpected error fetching kiosk recharges: {e}"


# ---------------------------------------------------------------------------
# POS Transactions tool
# ---------------------------------------------------------------------------

_POS_TRANSACTIONS_URL = (
    SETOMATIC_BASE_URL
    + "/api/POS/GetPOSTransactionReport"
)
_POS_OPERATOR_ID = 4


@tool(args_schema=POSTransactionsSchema)
def get_pos_transactions(
    start_date: str,
    end_date: str,
    card_code: int = 17,
    order_type: int = 1,
    account_type: int = 1,
    card_no: str | None = None,
    location_id: int | None = None,
    pos_id: str | None = None,
    page_size: int = 5,
    page_no: int = 1,
) -> str:
    """
    Use this tool when the operator asks about POS (Point of Sale) transactions,
    sales reports, or order data within a date range.

    Supports filtering by payment type (loyalty/credit/cash), order type
    (all/sale/WDF-PUD), customer type (all/commercial/non-commercial),
    specific card number, location, or POS terminal.

    Args:
        start_date: Start date (YYYY-MM-DD). Required.
        end_date: End date (YYYY-MM-DD). Required.
        card_code: Payment type — 17=Loyalty Card (default), 19=Credit Card, 20=Cash.
        order_type: Order type — 1=All (default), 2=Sale only, 3=WDF and PUD.
        account_type: Customer type — 1=All (default), 2=Commercial only, 3=Non-commercial only.
        card_no: Optional filter by specific card number.
        location_id: Optional filter by location ID.
        pos_id: Optional filter by POS terminal ID.
        page_size: Number of results per page (1-100, default 20).
    """
    try:
        body = {
            "UserId": _POS_OPERATOR_ID,
            "StartDate": start_date,
            "EndDate": end_date,
            "CardCode": str(card_code),
            "CardNo": card_no,
            "LocationId": location_id,
            "PageNo": page_no,
            "PageSize": page_size,
            "Ordertype": order_type,
            "AccountType": account_type,
            "POSID": pos_id,
        }
        params = {
            "UserId": _POS_OPERATOR_ID,
            "StartDate": start_date,
            "EndDate": end_date,
            "CardCode": card_code,
            "Ordertype": order_type,
            "AccountType": account_type,
        }
        logger.info("[get_pos_transactions] GET %s | Params: %s", _POS_TRANSACTIONS_URL, params)

        response = requests.get(
            _POS_TRANSACTIONS_URL,
            params=params,
            json=body,
            timeout=(10.0, 15.0),
        )
        logger.info("[get_pos_transactions] Response [%s]: %s", response.status_code, response.text[:500])

        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "Instruct the user that the system is temporarily down."
            )

        if 400 <= response.status_code < 500:
            return f"API Error: The request was rejected. Details: {response.text}"

        payload = response.json()
        data = payload.get("data") or payload if isinstance(payload, list) else payload.get("data")

        if not data:
            card_type_names = {17: "Loyalty Card", 19: "Credit Card", 20: "Cash"}
            return (
                f"No POS transactions found between {start_date} and {end_date} "
                f"for payment type '{card_type_names.get(card_code, card_code)}'. "
                "Try widening the date range or changing the filters."
            )

        records = data if isinstance(data, list) else [data]
        records.sort(
            key=lambda r: r.get("transactiondatetime") or r.get("transactionDate") or r.get("orderDate") or "",
            reverse=True,
        )

        total = len(records)
        start_idx = (page_no - 1) * page_size
        page_records = records[start_idx : start_idx + page_size]

        if not page_records:
            return f"No more POS transaction records to show (page {page_no} is empty)."

        card_type_names = {17: "Loyalty Card", 19: "Credit Card", 20: "Cash"}
        order_type_names = {1: "All", 2: "Sale only", 3: "WDF & PUD"}
        acct_type_names = {1: "All Customers", 2: "Commercial", 3: "Non-commercial"}

        lines = [
            f"**POS Transaction Report** ({start_date} to {end_date})\n"
            f"Payment: {card_type_names.get(card_code, card_code)} | "
            f"Order Type: {order_type_names.get(order_type, order_type)} | "
            f"Customer: {acct_type_names.get(account_type, account_type)}\n"
        ]
        for i, rec in enumerate(page_records, start=start_idx + 1):
            tx_date_raw = (
                rec.get("transactiondatetime") or rec.get("transactionDate") or rec.get("orderDate") or ""
            )
            tx_date = tx_date_raw.split("T")[0] if "T" in tx_date_raw else (tx_date_raw or "N/A")
            amount_raw = rec.get("transactionamount") if rec.get("transactionamount") is not None else rec.get("transactionAmount") if rec.get("transactionAmount") is not None else rec.get("amount") if rec.get("amount") is not None else rec.get("totalAmount")
            amount = f"${float(amount_raw):.2f}" if amount_raw is not None else "N/A"
            card = rec.get("cardno") or rec.get("cardNo") or rec.get("cardNumber") or "N/A"
            location = rec.get("locationname") or rec.get("locationName") or rec.get("location") or "N/A"
            tx_type = rec.get("transactiontype") or rec.get("transactionType") or ""
            type_label = f" ({tx_type})" if tx_type else ""
            lines.append(
                f"{i}.{type_label} Amount: {amount} | Date: {tx_date} | "
                f"Card: {card} | Location: {location}"
            )

        shown = len(page_records)
        remaining = total - (start_idx + shown)
        if remaining > 0:
            lines.append(
                f"\nShowing {shown} of {total} records. "
                f"{remaining} more records are available. "
                f"Say \"show more\" to view the next {page_size} records."
            )
        else:
            lines.append(f"\nShowing all {total} records.")

        return "\n".join(lines)

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "Instruct the user to try again in five minutes."
        )
    except (KeyError, ValueError, TypeError) as e:
        return f"Failed to parse POS transactions response: {e}"
    except Exception as e:
        return f"Unexpected error fetching POS transactions: {e}"


# ---------------------------------------------------------------------------
# Remote Device Command tool
# ---------------------------------------------------------------------------

_REMOTE_DEVICE_URL = (
    SETOMATIC_BASE_URL
    + "/api/Kiosk/SendCommondToRemoteDevice"
)
_REMOTE_OPERATOR_ID = 4


@tool(args_schema=RemoteDeviceCommandSchema)
def send_remote_device_command(
    device_id: str,
    command: str,
    amount: float = 0,
) -> str:
    """
    Use this tool to send a remote command to a kiosk device. Supports two commands:
      - 'Reboot': Restart the target device (amount must be 0).
      - 'Dispense': Dispense a loyalty card from the device (amount must be > 0).

    IMPORTANT: This is a destructive action. The LLM MUST confirm with the operator
    before calling this tool. Only call after receiving explicit operator confirmation
    (e.g., "yes, reboot device ABC123").

    Args:
        device_id: The target device ID/IMEI to send the command to.
        command: 'Dispense' or 'Reboot'.
        amount: Dollar amount for card dispense (must be > 0 for Dispense, 0 for Reboot).
    """
    try:
        if command == "Dispense" and amount <= 0:
            return (
                "Validation Error: For 'Dispense' command, amount must be greater than 0. "
                "Please ask the operator for the card value to dispense."
            )
        if command == "Reboot" and amount != 0:
            amount = 0

        body = {
            "operatorId": _REMOTE_OPERATOR_ID,
            "deviceId": device_id,
            "command": command,
            "amount": amount,
        }
        logger.info("[send_remote_device_command] POST %s | Body: %s", _REMOTE_DEVICE_URL, body)

        response = requests.post(
            _REMOTE_DEVICE_URL,
            json=body,
            timeout=(10.0, 15.0),
        )
        logger.info("[send_remote_device_command] Response [%s]: %s", response.status_code, response.text[:500])

        if response.status_code >= 500:
            return (
                f"System Error: Backend server failure ({response.status_code}). "
                "The device command could not be sent. Instruct the user to try again later."
            )

        if 400 <= response.status_code < 500:
            return f"API Error: The command was rejected. Details: {response.text}"

        payload = response.json()
        message = payload.get("message") or payload.get("Message") or "Command sent successfully."

        action_desc = "reboot" if command == "Reboot" else f"dispense a loyalty card (${amount:.2f})"
        return (
            f"Successfully sent '{command}' command to device '{device_id}'. "
            f"Action: {action_desc}. Server response: {message}"
        )

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return (
            "System Error: Unable to connect to the backend API. "
            "The device command could not be sent. Instruct the user to try again in five minutes."
        )
    except (KeyError, ValueError, TypeError) as e:
        return f"Failed to process remote device command response: {e}"
    except Exception as e:
        return f"Unexpected error sending remote command to device '{device_id}': {e}"


# Exported list for binding to LLM
SETOMATIC_TOOLS = [
    get_loyalty_balance,
    get_transaction_history,
    check_refund_eligibility,
    execute_refund,
    check_global_system_status,
    get_kiosk_purchases,
    get_kiosk_recharges,
    get_pos_transactions,
    send_remote_device_command,
]
