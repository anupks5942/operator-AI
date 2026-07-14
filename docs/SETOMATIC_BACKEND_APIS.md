# Setomatic Backend API Requirements — Operator AI Agent (Final)

**Purpose:** Every API the Operator AI Agent needs from the Setomatic backend team. Only APIs the agent actually calls (or will call) are listed. Portal-only, dashboard, reporting, and admin-panel APIs are excluded.

**Status legend:**
- **DONE** = Live on beta and integrated into the agent.
- No status = Backend has not delivered this API yet.

**Last updated:** July 2026

---

## Tier 1 — Core Agent APIs (this month)

> These are the **only** Setomatic POS APIs the agent's tool-calling layer (`src/agent/tools.py`) invokes. The agent cannot function without them.

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 1 | Loyalty Balance API | `GET /api/Transactions/CheckLoyaltyCardBalance` | Fetch loyalty card balance | Returns current balance, bonus balance, and total used amount for a loyalty card number scoped to an operator. Agent sends `OperatorId` + `LoyaltyCardNo`. | **DONE** | |
| 2 | Transaction Search API | `GET /api/Transactions/ViewAllTransactionSearch` | Search & fetch transactions | Returns a paginated list of transactions filtered by card number, date range, refund status, location, and amount. Agent sends `LoggedInUserId`, `LoyaltyCardNo`, `StartDate`, `EndDate`, `PageNo`, `PageSize`, `isRefund`, `IsFundAmountUsed`. Default 5 records/page with "show more" continuation. Each result must include `transactionDetailId` (required for refund flow; hidden from operator display). | **DONE** | |
| 3 | Refund Validation API | `GET /api/Transactions/RefundEligibility` | Validate refund eligibility | Checks if a specific transaction is eligible for refund (e.g., within 30-day window, not already refunded). Returns eligibility status (`isEligible`) and reason. Agent sends `transactionDetailId` + `OperatorId`. | | |
| 4 | Refund Transaction API | `GET /api/Transactions/RefundProcessing` | Execute refund | Processes the actual refund for a validated transaction. Returns a refund receipt identifier. Agent sends `transactionDetailId` + `OperatorId`. Must only succeed after `RefundEligibility` confirmed `isEligible=true`. | | |

---

## How the Agent Uses These 4 APIs

The agent has a strict 3-step sequential refund workflow. Steps cannot be skipped or reordered.

```
Step 1: get_transaction_history  →  ViewAllTransactionSearch
        Fetches recent transactions for a loyalty card.
        Each row includes a transactionDetailId.

Step 2: check_refund_eligibility →  RefundEligibility
        Validates whether that transactionDetailId can be refunded.
        If isEligible=false → agent tells the operator and STOPS.

Step 3: execute_refund           →  RefundProcessing
        ONLY called if Step 2 returned isEligible=true.
        Returns refundReceipt number to the operator.
```

Balance lookups (`CheckLoyaltyCardBalance`) are independent — called whenever an operator asks about a card balance. The agent also uses this API to pre-validate that a card exists before fetching transactions.

---

## Agent-Side Fixes (NOT backend APIs)

These are code changes on our side, not new APIs for the backend team:

| Item | Current state | Fix |
|------|---------------|-----|
| `OperatorId` / `LoggedInUserId` hardcoded to `4` | All Setomatic API calls use `OperatorId=4` regardless of who's logged in | Pipe `operator_id` from `ChatRequest` through LangGraph state to tools — the portal already sends it |
| ~~Transaction date range locked to April 2026~~ | ~~Demo/staging window only~~ | **DONE** — `start_date` and `end_date` are now optional tool parameters. Operators can specify a custom date range; defaults to rolling 6-month window when omitted. |
| Bible PDF ingestion | Manual file placement in `KB/` folder | Ingest Brandon's 250-page PDF into ChromaDB — no backend endpoint needed |

---

## Tier 1B — Kiosk & POS APIs (July 2026)

> APIs delivered by backend team in July 2026 for kiosk operations and POS transaction reporting. All integrated into the agent.

| # | API | Endpoint | Purpose | Description | Status | Notes |
|---|-----|----------|---------|-------------|--------|-------|
| 5 | Kiosk Purchases API | `GET /api/Kiosk/GetKioskPurchasedLoyaltyCarddetails` | Fetch kiosk card purchase records | Returns loyalty cards purchased/sold at kiosks within a date range. Filters by UserId, date range, location, IMEI. API returns all records; agent paginates client-side (5/page). | **DONE** | Agent tool: `get_kiosk_purchases` |
| 6 | Kiosk Recharges API | `GET /api/Kiosk/GetKioskLoyaltyCardRechargedetails` | Fetch kiosk card recharge records | Returns loyalty cards recharged/topped-up at kiosks within a date range. Same filters as purchases. API returns all records; agent paginates client-side (5/page). | **DONE** | Agent tool: `get_kiosk_recharges` |
| 7 | Remote Device Command API | `POST /api/Kiosk/SendCommondToRemoteDevice` | Send remote command to kiosk device | Sends a 'Reboot' or 'Dispense' command to a target device. Dispense requires amount > 0. Agent uses 2-step confirmation flow before execution. | **DONE** | Agent tool: `send_remote_device_command` |
| 8 | POS Transaction Report API | `GET /api/POS/GetPOSTransactionReport` | Fetch POS transaction/order data | Returns POS transactions filtered by date range, CardCode (17=Loyalty/19=Credit/20=Cash), OrderType (1=All/2=Sale/3=WDF-PUD), AccountType (1=All/2=Commercial/3=Non-commercial). Optional: CardNo, LocationId, POSID. API returns all records; agent paginates client-side (5/page). | **DONE** | Agent tool: `get_pos_transactions` |

---

## Tier 2 — Future Platform APIs (Phase 5, not this month)

> These APIs power the **admin experience around the chatbot** (Brandon's KB Admin panel, QA review). The chatbot functions without them. Listed here so the backend team has visibility for future planning.

| # | API | Purpose | Description | Notes for Backend |
|---|-----|---------|-------------|-------------------|
| 9 | Feedback API | Capture operator feedback | Records thumbs up/down from the operator on individual AI responses, with optional free-text comment. Powers KB quality improvement loop. | |
| 10 | Conversation Logging API | Persist AI chat transcripts | Stores raw chat transcripts and session metadata for QA review and compliance auditing. Currently the agent uses in-memory storage (lost on restart). | |
| 11 | Manual Upload API | Upload KB documents | Endpoint for the Super Admin portal to upload new operator manuals (PDF/DOCX) and trigger re-ingestion into the agent's vector database. | |

---

## APIs NOT Required from Backend

These were in the original `API_Requirements.docx` but are **not needed** by the Operator AI Agent. Each has a specific reason.

### Agent-owned (handled internally, not Setomatic REST APIs)

| API | Reason |
|-----|--------|
| Email Notification API | Agent sends escalation emails directly via Mandrill SMTP. |
| SMS Notification API | Agent sends SMS alerts directly via Twilio. |
| Ticket Creation API | Agent generates ticket IDs (`TKT-{uuid}`) locally and includes them in escalation emails/SMS. |
| Escalation Logging API | Escalation data is in the email/SMS body. No separate logging endpoint needed. |
| Escalation Summary API | AI-generated summary is embedded in the escalation email body. |
| Interaction Audit API | Agent logs actions via structured Python logging. |
| System Status API | Already integrated — agent scrapes `setomaticsystems.com/status` directly. |

### Portal scope (portal has this data, chatbot doesn't need it)

| API | Reason |
|-----|--------|
| Operator Profile API | Portal already sends `operator_id`, `operator_name`, `operator_email`, `operator_phone` in every chat request. |
| Role / Permission API | Backend should enforce permissions on its own refund APIs. Portal controls which operators access the chatbot. |
| Operator Details API | Portal has operator account data. Agent doesn't need a separate lookup. |
| Location List / Details APIs | Portal has location data. Agent answers location/pricing questions via RAG from operator manuals. |

### Redundant with existing DONE APIs

| API | Reason |
|-----|--------|
| Transaction Details API | `ViewAllTransactionSearch` already returns `transactionDetailId`, datetime, amount, type, and location per row. |
| Transaction Status API | Transaction state is included in `ViewAllTransactionSearch` results. |
| Transaction History API | Same endpoint as `ViewAllTransactionSearch` — redundant. |
| Refund Status API | Refund result is returned in real-time during the same session. `ViewAllTransactionSearch` with `isRefund=true` shows completed refunds. |
| Refund History API | `ViewAllTransactionSearch` with `isRefund=true` already returns refunded transactions. |
| Loyalty Card Lookup API | `CheckLoyaltyCardBalance` returns data for valid cards and empty for invalid ones — sufficient for card validation. |
| Loyalty Transaction History API | Redundant with `ViewAllTransactionSearch` filtered by `LoyaltyCardNo`. |

### Portal admin actions (not chatbot scope)

| API | Reason |
|-----|--------|
| Loyalty Recharge API | Operators recharge cards on the portal, not via chatbot. Brandon's matrix: "Recharge Failure" = troubleshooting RAG, not an API action. |
| Loyalty Registration API | Brandon's matrix: "Card Registration" = portal guidance. Agent gives instructions, not API calls. |
| Loyalty Activation / Deactivation API | Portal admin action. Not in Brandon's intent matrix. |
| Pricing Configuration API | Agent answers pricing questions via RAG from manuals. |
| Store Configuration API | Portal admin scope. |

### Out of scope

| API | Reason |
|-----|--------|
| All 6 Reporting APIs (Revenue, Daily, Machine, Location, Refund, Loyalty) | Portal dashboard features. The chat agent does not generate reports. |
| Reload Center API | Future scope / portal. |
| KB Search / Document Metadata / KB Versioning APIs | Agent queries its vector database (ChromaDB) directly. These would serve an admin panel, not the chatbot. |
| Live machine telemetry / hub status / kiosk hardware | Explicitly forbidden. Agent has a guardrail node that refuses these requests. |

---

## Summary

| Tier | APIs | Done | To Build |
|------|------|------|----------|
| Tier 1 — Core Agent | 4 | 2 | **2** |
| Tier 1B — Kiosk & POS (July 2026) | 4 | 4 | 0 |
| Tier 2 — Future Platform (Phase 5) | 3 | 0 | 3 |
| **Total** | **11** | **6** | **5** |

**Immediate action for backend team:** Deliver `RefundEligibility` and `RefundProcessing` on beta. Once ready, agent switches from mock server to live (`USE_MOCK_REFUNDS=false`) and refund workflow is fully operational.
