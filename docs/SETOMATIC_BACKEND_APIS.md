# Setomatic Backend API Requirements — Operator AI Agent (Final)

**Purpose:** Every API the Operator AI Agent needs from the Setomatic backend team. APIs that serve only the portal dashboard, admin panel, or reporting UI are excluded — they are not consumed by the AI agent.

**Status legend:**
- **DONE** = API is live on beta and integrated into the agent.
- No status = Backend has not delivered this API yet.

**Last updated:** July 2026

---

## Sprint 1 — MVP Critical Blockers

> Do **not** proceed to other sections until these 4 APIs are delivered, tested, and deployed on beta. The agent's core workflows are blocked without them.

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 1 | Loyalty Balance API | `GET /api/Transactions/CheckLoyaltyCardBalance` | Fetch loyalty card balance | Returns current balance, bonus balance, and total used amount for a loyalty card number scoped to an operator. | **DONE** | |
| 2 | Transaction Search API | `GET /api/Transactions/ViewAllTransactionSearch` | Search & fetch transactions | Returns a paginated list of transactions filtered by card number, date range, refund status, location, amount, etc. Also serves as the agent's transaction history and refund-transaction lookup. | **DONE** | |
| 3 | Refund Validation API | `GET /api/Transactions/RefundEligibility` | Validate refund eligibility | Checks if a specific transaction is eligible for refund (e.g., within 30-day refund window, not already refunded). Returns eligibility status and reason. | | |
| 4 | Refund Transaction API | `GET /api/Transactions/RefundProcessing` | Execute refund | Processes the actual refund for a validated transaction. Returns a refund receipt identifier. | | |

---

## Sprint 2 — Authentication, Scoping & System Status

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 5 | Operator Profile API | TBD | Fetch logged-in operator details | Returns the authenticated operator's ID, operator code, assigned locations, display name, email, and phone number. | | |
| 6 | Role / Permission API | TBD | Check operator permissions | Verifies whether an operator has permission for specific actions (e.g., process refunds, view transactions, recharge cards). | | |
| 7 | System Status API | TBD | Check global system status | Returns current Setomatic/SpyderWash operational status (operational, degraded, outage) with active incident details and timestamps. | | |

---

## Phase 2 — Extended Transaction & Refund Capabilities

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 8 | Transaction Details API | TBD | Fetch single transaction metadata | Returns comprehensive details for a specific transaction ID — payment method, machine ID, location, timestamps, status. | | |
| 9 | Transaction Status API | TBD | Fetch transaction state | Returns the current state of a transaction: success, failed, pending, or refunded. | | |
| 10 | Refund Status API | TBD | Check refund processing state | Returns whether a previously initiated refund has been processed, is pending, or failed at the payment gateway. | | |
| 11 | Refund History API | TBD | Fetch refund audit trail | Returns a historical log of all refunds issued by an operator, with amounts, timestamps, and receipt numbers. | | |

---

## Phase 2 — Extended Loyalty Card Capabilities

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 12 | Loyalty Card Lookup API | TBD | Fetch card details | Returns card status (active/deactivated), assigned customer name, base location, and registration date using exact card number. | | |
| 13 | Loyalty Transaction History API | TBD | Fetch card-specific usage history | Returns detailed recharge and usage history for a specific loyalty card — distinguishes recharges, washes, and adjustments. | | |
| 14 | Loyalty Recharge API | TBD | Reload card balance | Processes a manual recharge/reload of a loyalty card with a specified dollar amount. | | |
| 15 | Loyalty Registration API | TBD | Register new loyalty card | Assigns a new or existing loyalty card to a customer, employee, or technician profile. | | |
| 16 | Loyalty Activation / Deactivation API | TBD | Toggle card active state | Activates or deactivates a loyalty card (e.g., block a lost card, reactivate a returned card). | | |

---

## Phase 2 — Operator & Location Context

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 17 | Operator Details API | TBD | Fetch operator account info | Returns overarching operator account details — company name, global settings, contact information. | | |
| 18 | Location List API | TBD | Fetch operator's locations | Returns an array of all physical store locations managed by the authenticated operator, with location IDs and names. | | |
| 19 | Location Details API | TBD | Fetch single location config | Returns configuration, address, operating hours, and parameters for a specific location. | | |

---

## Phase 3 — Escalation & Audit Trail

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 20 | Ticket Creation API | TBD | Create support ticket | Creates a formal ticket in the helpdesk system containing the AI-generated issue summary, operator info, and conversation transcript. Returns a persistent ticket ID. | | |
| 21 | Escalation Logging API | TBD | Record escalation events | Logs the escalation event — timestamp, destination (email/SMS), ticket ID, and outcome — in the database for auditing. | | |
| 22 | Conversation Logging API | TBD | Persist AI chat transcripts | Stores the raw AI chat transcript and session state for QA review and compliance auditing. | | |
| 23 | Interaction Audit API | TBD | Log specific AI actions | Records each discrete agent action (balance lookup, refund executed, escalation triggered) with timestamps, parameters, and results. | | |
| 24 | Escalation Summary API | TBD | Persist escalation summaries | Stores the AI-generated compressed issue summary that accompanies human handoff, linked to the ticket ID. | | |
| 25 | Feedback API | TBD | Capture operator feedback | Records thumbs up/down from the operator on individual AI responses, with optional free-text comment. | | |

---

## Phase 4 — Knowledge Base Administration

| # | API | Endpoint | Purpose | Description | Status | Notes for Backend |
|---|-----|----------|---------|-------------|--------|-------------------|
| 26 | Manual Upload API | TBD | Upload KB documents | Endpoint to ingest new operator manuals (PDF/DOCX) into the agent's vector database. Returns upload status and document metadata. | | |

---

## APIs Explicitly NOT Required from Backend

These capabilities are either **agent-owned** (handled internally by the AI agent) or **out of scope** for the operator chat agent. Do **not** build these as Setomatic REST APIs for the agent.

| Capability | Reason NOT Required |
|------------|---------------------|
| Email Notification API | Agent-owned — sends escalation emails directly via Mandrill SMTP. Not a Setomatic REST call. |
| SMS Notification API | Agent-owned — sends SMS alerts directly via Twilio. Not a Setomatic REST call. |
| Revenue Report API | Portal/dashboard scope — the chat agent does not generate reports. |
| Daily Transaction Report API | Portal/dashboard scope. |
| Machine Revenue API | Portal/dashboard scope. |
| Location Revenue API | Portal/dashboard scope. |
| Refund Report API | Portal/dashboard scope. |
| Loyalty Usage Report API | Portal/dashboard scope. |
| Pricing Configuration API | Portal admin scope — agent answers pricing questions via RAG from operator manuals. |
| Store Configuration API | Portal admin scope. |
| Kiosk Transaction API | Future scope / portal — no agent integration path planned. |
| Reload Center API | Future scope / portal. |
| KB Search API | Agent-internal — the agent queries its vector database (ChromaDB) directly. |
| Document Metadata API | Agent-internal. |
| KB Versioning API | Agent-internal. |
| Live machine telemetry / individual machine status | Explicitly forbidden — agent has a guardrail that refuses these requests. |
| Live hub status / port-level diagnostics | Explicitly forbidden — same guardrail. |
| Kiosk hardware status / kiosk error logs | Not integrated — no tools or intent for this. |
| Raw backend/system errors | Blocked — agent wraps all API errors in graceful user-facing messages. |

---

## Summary

| Priority | APIs | Done | Remaining |
|----------|------|------|-----------|
| Sprint 1 — MVP Blockers | 4 | 2 | 2 |
| Sprint 2 — Auth & Scoping | 3 | 0 | 3 |
| Phase 2 — Transactions & Refunds | 4 | 0 | 4 |
| Phase 2 — Loyalty | 5 | 0 | 5 |
| Phase 2 — Operator & Location | 3 | 0 | 3 |
| Phase 3 — Escalation & Audit | 6 | 0 | 6 |
| Phase 4 — KB Admin | 1 | 0 | 1 |
| **Total** | **26** | **2** | **24** |
