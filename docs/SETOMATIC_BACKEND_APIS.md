# Setomatic Backend API Requirements

Maps **`SendAnywhere_546287/API_Requirements.docx`** to what the Operator Agent **calls today**, what **blocks UAT/prod**, and the full backend backlog for the Setomatic team.

**This is not the Agent API.** For the chat contract (`POST /api/v1/agent/chat`), see [API.md](API.md).

**Last updated:** July 2026  
**Owner (backend delivery):** Setomatic backend team  
**Owner (agent integration):** dev1

---

## Two API surfaces

| Surface | Base URL | Purpose | Doc |
|---------|----------|---------|-----|
| **Operator Agent API** | `:8000` (this repo) | Web chat → LangGraph | [API.md](API.md) |
| **Setomatic POS / portal APIs** | `SETOMATIC_BASE_URL` (beta/prod) | Tools: loyalty, transactions, refunds | This document |

The agent does **not** handle login. The .NET portal authenticates the operator and passes `operator_id` (+ contact fields) to the agent API. Setomatic must later provide **Operator Profile** and **Role/Permission** APIs so the portal can scope tool calls correctly.

---

## Sprint 1 — critical blockers (MVP)

From the requirements doc: **do not proceed to other endpoints until these four are delivered, tested, and deployed.**

| Requirement (doc name) | Agent tool | Setomatic endpoint (agent code) | Status | Notes |
|------------------------|------------|----------------------------------|--------|-------|
| **Loyalty Balance API** | `get_loyalty_balance` | `GET /api/Transactions/CheckLoyaltyCardBalance` | **Partial — live on beta** | Uses `OperatorId` + `LoyaltyCardNo`. Agent hardcodes `OperatorId=4` — Phase 1 fix |
| **Transaction Search / Lookup API** | `get_transaction_history` | `GET /api/Transactions/ViewAllTransactionSearch` | **Partial — live on beta** | Doc: search by **last 4** of card; agent sends **full** `LoyaltyCardNo`. Doc: general search; agent uses fixed date window + pagination. `isRefund` param filters refunded vs normal transactions |
| **Refund Validation API** | `check_refund_eligibility` | `GET /api/Transactions/RefundEligibility` | **Blocked — mock only** | `USE_MOCK_REFUNDS=true` default → `:8001` mock. Beta API **not ready** |
| **Refund Transaction API** | `execute_refund` | `GET /api/Transactions/RefundProcessing` | **Blocked — mock only** | Same as above |

**Agent refund workflow (implemented):** transaction history → eligibility → execute (never skip eligibility). See [tools.py](../src/agent/tools.py).

**Unblock criteria for UAT refunds:** Setomatic delivers + documents beta RefundEligibility + RefundProcessing; dev1 sets `USE_MOCK_REFUNDS=false` and validates end-to-end.

---

## Implemented in agent today (Setomatic calls)

| Tool | HTTP | Key parameters (today) | Env |
|------|------|------------------------|-----|
| `get_loyalty_balance` | GET `.../CheckLoyaltyCardBalance` | `OperatorId`, `LoyaltyCardNo` | Always live `SETOMATIC_BASE_URL` |
| `get_transaction_history` | GET `.../ViewAllTransactionSearch` | `LoggedInUserId`, `LoyaltyCardNo`, `StartDate`, `EndDate`, `PageNo`, `PageSize`, `isRefund` | Always live |
| `check_refund_eligibility` | GET `.../RefundEligibility` | `transactionDetailId`, `OperatorId` | Mock or live per `USE_MOCK_REFUNDS` |
| `execute_refund` | GET `.../RefundProcessing` | `transactionDetailId`, `OperatorId` | Mock or live per `USE_MOCK_REFUNDS` |
| `check_global_system_status` | GET scrape `setomaticsystems.com/status` | N/A (not a Setomatic REST API) | Live scrape |

Default base URL: `https://betasetomaticposwebapplication.spyderwash.com` — [config.py](../src/config.py).

### Known agent-side gaps (not Setomatic blockers)

| Gap | Impact | Phase |
|-----|--------|-------|
| `OperatorId` / `LoggedInUserId` hardcoded `4` | Wrong operator in prod | Phase 1 — [ROADMAP.md](ROADMAP.md) |
| Transaction dates locked to `2026-04-01`–`2026-04-30` | Demo/staging window only | Phase 1 — use rolling 6-month window |
| Full card number vs last-4 search | May not match doc’s “last 4 digits” UX | Align with Setomatic API contract |
| Mock server loyalty/transaction routes | **Unused** by tools — only refund mocks wired | [mock_server.py](../src/api/mock_server.py) |

---

## Full backend backlog (requirements doc)

Status for **Operator Agent MVP** unless noted.

### 1. Authentication & session

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Operator Profile API | **Yes** (via portal → agent) | **Planned** | Portal passes `operator_id`, name, email, phone to agent API today |
| Role/Permission API | **Yes** (refunds) | **Planned** | Agent has no permission check before refund tools |

Login/logout: **N/A** — agent runs inside authenticated portal per requirements doc.

### 2. Transaction APIs

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| View All Transactions API | **Partial** | **Partial** | Mapped to `ViewAllTransactionSearch` |
| Transaction Details API | **Future** | **Not integrated** | Single-tx metadata |
| Transaction Search API (filters) | **Future** | **Not integrated** | Date/payment/amount filters |
| Transaction Status API | **Future** | **Not integrated** | |
| Transaction History API | **Partial** | **Partial** | Overlaps ViewAllTransactionSearch tool |

### 3. Refund APIs

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Refund Validation API | **Yes** | **Mock only** | Sprint 1 blocker |
| Refund Transaction API | **Yes** | **Mock only** | Sprint 1 blocker |
| Refund Status API | **Future** | **Not integrated** | |
| Refund History API | **Future** | **Not integrated** | |

### 4. Loyalty card APIs

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Loyalty Balance API | **Yes** | **Partial — live** | Sprint 1 |
| Loyalty Card Lookup API | **Future** | **Not integrated** | Status, assigned user, location |
| Loyalty Transaction History API | **Partial** | **Partial** | Via transaction search tool |
| Loyalty Recharge API | **Future** | **Not integrated** | |
| Loyalty Registration API | **Future** | **Not integrated** | |
| Loyalty Activation/Deactivation API | **Future** | **Not integrated** | |

### 5. Reporting APIs

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Revenue / Daily / Machine / Location / Refund / Loyalty reports | **No (MVP)** | **Not integrated** | Out of operator chat scope for v1 |

### 6. Operator & location APIs

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Operator Details API | **Future** | **Not integrated** | |
| Location List / Details / Store config / Pricing | **Future** | **Not integrated** | Intent Matrix has pricing rows — RAG today |

### 7. Kiosk & reload center (future scope)

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Kiosk Transaction API | **Deferred** | **Not integrated** | Doc marks future scope |
| Reload Center API | **Deferred** | **Not integrated** | |

### 8. Notification & escalation

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Email Notification API | **No** | **Agent-owned** | Mandrill via [notifications.py](../src/services/notifications.py) — not Setomatic REST |
| SMS Notification API | **No** | **Agent-owned** | Twilio via agent — not Setomatic REST |
| Ticket Creation API | **Future** | **Partial** | Agent generates ticket ID locally; no helpdesk API |
| Escalation Logging API | **Future** | **Not integrated** | Email/SMS only today |

### 9. AI conversation logging

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Conversation Logging API | **Future** | **Not integrated** | MemorySaver in-process only |
| Interaction Audit API | **Future** | **Not integrated** | |
| Escalation Summary API | **Future** | **Partial** | Summary in escalation email body |
| Feedback API (thumbs up/down) | **Yes (Phase 5)** | **Not integrated** | Powers Brandon KB Admin feedback log — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |

### 10. Knowledge base / documentation (optional)

| API (doc) | Agent needs? | Status | Notes |
|-----------|--------------|--------|-------|
| Manual Upload / KB Search / Metadata / Versioning | **Yes (Phase 5)** | **Not integrated** | Replaces email + manual re-ingest; pairs with KB Admin — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |

---

## APIs explicitly NOT required (guardrails)

Per requirements doc — **must not** be exposed to the agent. Enforced in code:

| Forbidden capability | Agent behavior | Code |
|---------------------|----------------|------|
| Live machine telemetry / individual machine status | Static refusal | `guardrail_node` — [nodes.py](../src/agent/nodes.py) |
| Live hub status / port-level diagnostics | Static refusal | Same guardrail |
| Kiosk hardware status / kiosk error logs | Not integrated | No tools |
| Internal infrastructure monitoring | Not integrated | Global status scrape is **public** status page only |
| Raw backend/system errors to operator | Graceful tool error strings | [tools.py](../src/agent/tools.py) |

See [PRD.md](PRD.md) §4 and [INTENT_MATRIX.md](INTENT_MATRIX.md).

---

## Expected workflow (requirements doc)

```
Operator query
  → Intent classification (router)
  → Guardrail & outage evaluation
  → Knowledge retrieval and/or API decision
  → API call (if required)
  → Response generation
  → Escalation (if unresolved)
```

Implemented in [graph.py](../src/agent/graph.py). Detail: [ARCHITECTURE.md](ARCHITECTURE.md), [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## Environment & testing

| Goal | Config |
|------|--------|
| Loyalty + transactions against beta | `SETOMATIC_BASE_URL` → beta; mock server optional |
| Refunds in dev | `USE_MOCK_REFUNDS=true`, run `:8001` mock — [RUNBOOK.md](RUNBOOK.md) |
| Refunds in UAT/prod | `USE_MOCK_REFUNDS=false` when Sprint 1 refund APIs ready |

Mock refund endpoints (used by tools):  
`GET /api/Transactions/RefundEligibility`, `GET /api/Transactions/RefundProcessing` on `:8001`.

---

## Maintenance

When Setomatic delivers or changes an API:

1. Update the **Sprint 1** and **Implemented** tables in this doc.
2. Update [tools.py](../src/agent/tools.py) and [PRD.md](PRD.md) feature matrix.
3. Update [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) if vendor scope shifts.
4. Add integration tests when live refund APIs are available.

---

## Related documents

- [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) — Feedback & KB APIs → Brandon Admin UX
- [API.md](API.md) — Operator Agent REST contract (`:8000`)
- [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) — full vendor requirements traceability
- [ROADMAP.md](ROADMAP.md) — Phase 1 `operator_id`, refund unblock
- [PRD.md](PRD.md) — feature status matrix
- [ENVIRONMENT.md](ENVIRONMENT.md) — `SETOMATIC_BASE_URL`, `USE_MOCK_REFUNDS`
