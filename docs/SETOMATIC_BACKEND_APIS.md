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
| 2 | Transaction Search API | `GET /api/Transactions/ViewAllTransactionSearch` | Search & fetch transactions | Returns a paginated list of transactions filtered by card number, date range, refund status, location, and amount. Agent sends `LoggedInUserId`, `LoyaltyCardNo`, `StartDate`, `EndDate`, `PageNo`, `PageSize`, `isRefund`, `IsFundAmountUsed`. Default 5 records/page with "show more" continuation. `transactionDetailId` kept internal only (not shown to operators). | **DONE** | |

---

## Refund policy (Brandon — Jul 13, 2026) — NO agent-executed refunds

Backend stated that live refund processing needs many payment-gateway parameters and is too complex/risky for the chat agent. **Brandon approved** the following approach:

> The agent must **only guide** operators with instructions to process a refund on the **SpyderWash portal**. The agent must **not** call refund APIs or execute refunds itself (avoids wrong-transaction refunds).

| Decision | Detail |
|----------|--------|
| Agent role | RAG / Bible guidance → portal steps for refund submission |
| Agent must NOT | Call `RefundEligibility` / `RefundProcessing` or any refund execute tools |
| KB source | Bible will include refund-request instructions — **Brandon owns KB content**; Chetu must not invent portal how-to docs |
| Code | Refund execute tools and mock `:8001` server **removed** from the repo |

`ViewAllTransactionSearch` with `isRefund=true` may still be used to **look up** refunded transaction history (read-only). That is not the same as processing a refund.

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
| 8 | POS Transaction Report API | `GET /api/POS/GetPOSTransactionReport` | Fetch POS transaction/order data | Returns POS transactions filtered by date range, CardCode (17=Loyalty/19=Credit/20=Cash), OrderType (1=All/2=Sale/3=WDF-PUD), AccountType (1=All/2=Commercial/3=Non-commercial). Optional: CardNo, LocationId, POSID. API returns all records; agent paginates client-side (5/page). When a card filter is provided (including masked last-4), agent also filters client-side so unmatched cards never show another card's rows. | **DONE** | Agent tool: `get_pos_transactions` |

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
| Role / Permission API | Portal controls which operators access the chatbot. Refunds are portal-owned (not agent APIs). |
| Operator Details API | Portal has operator account data. Agent doesn't need a separate lookup. |
| Location List / Details APIs | Portal has location data. Agent answers location/pricing questions via RAG from operator manuals. |

### Redundant with existing DONE APIs

| API | Reason |
|-----|--------|
| Transaction Details API | `ViewAllTransactionSearch` already returns `transactionDetailId`, datetime, amount, type, and location per row. |
| Transaction Status API | Transaction state is included in `ViewAllTransactionSearch` results. |
| Transaction History API | Same endpoint as `ViewAllTransactionSearch` — redundant. |
| Refund Eligibility / Processing APIs | **Not required for the agent** — Brandon approved portal-guided refunds only (Jul 2026). |
| Refund Status API | Operators track refunds on the portal. Agent may show refund history via `ViewAllTransactionSearch` (`isRefund=true`) as read-only lookup. |
| Refund History API | `ViewAllTransactionSearch` with `isRefund=true` already returns refunded transactions (read-only). |
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
| Reload Center API | Future scope / portal. |
| KB Search / Document Metadata / KB Versioning APIs | Agent queries its vector database (ChromaDB) directly. These would serve an admin panel, not the chatbot. |
| Live machine telemetry / hub status / kiosk hardware | Explicitly forbidden. Agent has a guardrail node that refuses these requests. |

---

## Tier 1C — Reports APIs (July 2026)

> 7 reporting endpoints integrated as a unified `get_report` tool. Operators can ask for revenue/attendant/promotional-fund/POS reports via the chatbot.

| # | API | Endpoint | Purpose | Description | Status | Notes |
|---|-----|----------|---------|-------------|--------|-------|
| 9 | Revenue by Location | `GET /api/Reports/GetRevenueByLocationReport` | Revenue breakdown per location | Returns totalRevenue, percent, grandTotal, totalCash per location. Params: locations, fromDate, toDate, operatorId, isFundUsed. | **DONE** | Agent tool: `get_report(report_type='revenue_by_location')` |
| 10 | Revenue by Position | `GET /api/Reports/GetRevenueByPositionReport` | Revenue per machine position | Returns propertyValue, modelNumber, vendPrice, cash/credit/loyalty/emv per position. Params: operatorId, locations, fromDate, toDate, propertyId, propertyValues, isDeletedMachineIncluded, isFundUsed. | **DONE** | Agent tool: `get_report(report_type='revenue_by_position')` |
| 11 | Revenue by Machine Type | `GET /api/Reports/GetRevenueByMachineTypeReport` | Revenue per machine model | Returns modelNo, vendPrice, machineQuantity, cash/credit/loyalty/emv. Params: modelId, locations, fromDate, toDate, operatorId, isFundUsed. | **DONE** | Agent tool: `get_report(report_type='revenue_by_machine_type')` |
| 12 | Revenue by Month | `GET /api/Reports/GetRevenueByMonthOfYearReport` | Monthly revenue breakdown | Returns monthText, cash, creditCard, loyaltyCard, emvCard. Params: locations, fromDate, toDate, operatorId, isFundUsed. | **DONE** | Agent tool: `get_report(report_type='revenue_by_month')` |
| 13 | Attendant Detail | `GET /api/Reports/GetAttendantDetailReport` | Attendant activity report | Returns attendant activity/time data. Params: locations, attendants, fromDate, toDate. | **DONE** | Agent tool: `get_report(report_type='attendant_detail')` |
| 14 | Promotional Fund | `GET /api/Reports/GetRevenueByPromotionalFundReport` | Promotional fund usage | Returns position, modelNo, transactionAmount, refundedAmount, dateTime, locationName, cardNumber, transactionType. Params: locations, fromDate, toDate, operatorId. | **DONE** | Agent tool: `get_report(report_type='promotional_fund')` |
| 15 | POS Transactions Report | `GET /api/Reports/GetPosTransactionsReport` | POS gateway transactions | Returns POS transaction records filtered by loyaltyCard, dates, operator, location. Params: loyaltyCard, fromDate, toDate, operatorId, locations. | **DONE** | Agent tool: `get_report(report_type='pos_transactions')` |

---

## Summary

| Tier | APIs | Done | To Build |
|------|------|------|----------|
| Tier 1 — Core Agent (balance + transaction search) | 2 | 2 | **0** |
| Tier 1B — Kiosk & POS (July 2026) | 4 | 4 | 0 |
| Tier 1C — Reports (July 2026) | 7 | 7 | 0 |
| Tier 2 — Future Platform (Phase 5) | 3 | 0 | 3 |
| **Total** | **16** | **13** | **3** |

**Refunds:** No agent refund APIs. Guide operators via Bible/RAG to the SpyderWash portal. Bible refund content owned by Brandon (Jul 13, 2026).
