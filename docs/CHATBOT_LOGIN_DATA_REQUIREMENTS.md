# Chatbot Login-Time Data Requirements

**Audience:** Portal frontend (.NET / React) + Setomatic backend integrators  
**Source of truth:** `src/api/server.py` (`ChatRequest`), `src/agent/tools.py`, `docs/API.md`, `docs/SETOMATIC_BACKEND_APIS.md`  
**Last updated:** August 2026

---

## 1. What this document answers

1. At **portal login / chat open**, which operator fields must the frontend already have?
2. On every **`POST /api/v1/agent/chat`** call, which fields are required vs optional?
3. For each **Setomatic backend API** the agent calls, which parameters are required — and which of those should come from **login context** vs **chat conversation**?

---

## 2. Hard truth (read this first)

| Fact | Implication |
|------|-------------|
| Chatbot has **no separate login API**. | Portal login is owned by SpyderWash portal. Chat only receives operator context on each chat request. |
| `operator_id` is **required on chat API** and stored in agent state, but **tools still hardcode `OperatorId=4` / `UserId=4`**. | Until Phase 1 wiring is done, live tool calls are scoped to operator `4` even if another ID is sent. Frontend must still send the real `operator_id` now so escalation and future tool scoping work. |
| `operator_name` / `operator_email` / `operator_phone` are **optional in schema** but **strongly required for good escalations**. | If omitted, tickets show `"Unknown Operator"` / `unknown@operator.local` / `N/A`. |
| `passcode` is **not** on `ChatRequest` today. | Location-list tool asks the operator in chat. Prefer adding passcode (or pre-fetched location list) at login later. |
| `session_id` is **client-owned**. | Agent backend does not create or delete sessions. New ID = empty memory. |

---

## 3. Data needed at portal login / chat widget open

These fields should already be available from the **authenticated portal session** before the operator sends the first chat message.

### 3.1 Must have (frontend → agent on every chat request)

| Field | Type | Where it comes from | Why |
|-------|------|---------------------|-----|
| `operator_id` | `int` | Portal auth / logged-in user account ID | Scopes identity in agent state; **target** for all Setomatic `OperatorId` / `UserId` / `LoggedInUserId` / `operatorId` tool params |
| `session_id` | `string` (UUID) | Frontend generates once per chat widget session | LangGraph `thread_id` — multi-turn memory |
| `message` | `string` | Operator typed text (per turn) | The actual question |

### 3.2 Strongly recommended at login (pass on every chat request)

| Field | Type | Where it comes from | Why |
|-------|------|---------------------|-----|
| `operator_name` | `string` | Portal profile | Escalation email / ticket contact block |
| `operator_email` | `string` | Portal profile | Escalation email contact |
| `operator_phone` | `string` | Portal profile (E.164 preferred, e.g. `+15551234567`) | Escalation template + callback context |

### 3.3 Recommended to capture at login (not on ChatRequest yet — gap)

| Field | Type | Status | Why |
|-------|------|--------|-----|
| `passcode` | `string` | **Not on API today** — agent asks in chat for `get_operator_locations` | Avoids asking passcode again in chat; needed for `GET /api/POSController/GetUserAssignlocations` |
| Assigned `location_ids` | `int[]` | Not on API today | Prefills reports / machine config without asking "which location?" |
| Default `location_id` | `int` | Not on API today | Faster machine-config / POS filters |

### 3.4 Server-to-server auth (frontend BFF / .NET proxy → agent)

| Header | Required | Notes |
|--------|----------|-------|
| `X-API-Key` | Yes (if `API_KEY` is set in agent `.env`) | Validated by `verify_api_key`. Do **not** put this key in browser JS — proxy from .NET backend. |

### 3.5 Not needed at login for chatbot

| Item | Reason |
|------|--------|
| Loyalty card number | Collected in chat when operator asks about a card |
| Device IMEI / POS ID | Collected in chat when needed |
| Refund payment-gateway params | Agent does **not** execute refunds |
| Operator password / portal JWT | Portal auth only; agent does not validate portal tokens |
| Live machine telemetry | Out of scope / guardrailed |

---

## 4. Agent Chat API — request contract

**Endpoint:** `POST /api/v1/agent/chat`  
**Content-Type:** `application/json`

### 4.1 Request body

| Field | Type | Required | Source | Used for |
|-------|------|----------|--------|----------|
| `operator_id` | integer | **Yes** | Portal login | Agent state; escalation display; **should** scope Setomatic tools (Phase 1) |
| `session_id` | string | **Yes** | Frontend (UUID per widget session) | Conversation memory |
| `message` | string | **Yes** | Operator input | Current turn |
| `operator_name` | string | No* | Portal profile | Escalation email |
| `operator_email` | string | No* | Portal profile | Escalation email |
| `operator_phone` | string | No* | Portal profile | Escalation email / callback |
| `channel` | string | No (default `"chat"`) | Frontend | `"chat"` \| `"voice"` |

\*Optional in Pydantic schema, but **treat as required for production portal integration**.

### 4.2 Example — first message after login

```json
{
  "operator_id": 12345,
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "My washer won't start.",
  "operator_name": "Jane Operator",
  "operator_email": "jane@laundromat.example",
  "operator_phone": "+15551234567",
  "channel": "chat"
}
```

### 4.3 Response (relevant fields)

| Field | Meaning |
|-------|---------|
| `reply` | Text to show in chat UI |
| `detected_intent` | Router label |
| `requires_escalation` | `true` if escalation dispatched this turn |

### 4.4 Frontend ownership of `session_id`

| Event | Action |
|-------|--------|
| Chat widget open | Create UUID once; store in `sessionStorage` |
| Every message | Reuse same `session_id` + same operator contact fields |
| "New Chat" / widget close | Discard `session_id` → next open starts empty memory |
| Page refresh | Same tab session may continue (`sessionStorage` survives F5) |

---

## 5. Responsibility split

```
┌─────────────────────┐     login session      ┌──────────────────────┐
│  SpyderWash Portal  │ ─────────────────────► │  Chat widget / BFF   │
│  (.NET auth)        │  operator_id, name,    │  generates session_id│
│                     │  email, phone, (+opt   │  sends X-API-Key     │
│                     │   passcode, locations) │                      │
└─────────────────────┘                        └──────────┬───────────┘
                                                          │ POST /api/v1/agent/chat
                                                          ▼
                                               ┌──────────────────────┐
                                               │  Operator AI Agent   │
                                               │  (this repo)         │
                                               └──────────┬───────────┘
                                                          │ tools (OperatorId today=4)
                                                          ▼
                                               ┌──────────────────────┐
                                               │  Setomatic POS APIs  │
                                               └──────────────────────┘
```

| Layer | Owns |
|-------|------|
| **Portal frontend / BFF** | Login, profile fields, `session_id`, API key proxy, chat UI |
| **Operator AI agent** | Intent routing, RAG, tool calls, escalation email/SMS |
| **Setomatic backend** | Loyalty / transactions / kiosk / POS / reports / locations APIs |

---

## 6. API-by-API: required parameters

Legend for **Login?** column:

- **Login** = should come from authenticated portal session / chat request context (`operator_id`, etc.)
- **Chat** = operator says it in conversation (or LLM extracts it)
- **Agent default** = agent fills automatically
- **Hardcoded today** = code currently forces `4` — must become Login `operator_id`

---

### 6.0 Agent entry API (what frontend calls)

#### `POST /api/v1/agent/chat`

| Parameter | Required | Source | Notes |
|-----------|----------|--------|-------|
| `operator_id` | Yes | **Login** | Real logged-in operator account ID |
| `session_id` | Yes | **Frontend** | UUID; not from Setomatic |
| `message` | Yes | **Chat** | Per turn |
| `operator_name` | Recommended | **Login** | Escalation quality |
| `operator_email` | Recommended | **Login** | Escalation quality |
| `operator_phone` | Recommended | **Login** | Escalation / callback |
| `channel` | No | Frontend | Default `chat` |
| Header `X-API-Key` | Yes (prod) | **Backend/BFF secret** | Never expose in browser |

---

### 6.1 Tier 1 — Core

#### 1) Loyalty Balance — `GET /api/Transactions/CheckLoyaltyCardBalance`

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `OperatorId` | Yes | **Hardcoded `4`** | **Login → `operator_id`** |
| `LoyaltyCardNo` | Yes | **Chat** | Chat |

#### 2) Transaction Search — `GET /api/Transactions/ViewAllTransactionSearch`

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `LoggedInUserId` | Yes | **Hardcoded `4`** | **Login → `operator_id`** |
| `LoyaltyCardNo` | Yes | **Chat** | Chat |
| `StartDate` | Yes | Agent default (rolling 6 months) or Chat | Agent / Chat |
| `EndDate` | Yes | Agent default (today) or Chat | Agent / Chat |
| `PageNo` | Yes | Agent (`1`+) | Agent |
| `PageSize` | Yes | Agent (default 5) | Agent |
| `isRefund` | Yes | Agent / Chat | Agent / Chat |
| `IsFundAmountUsed` | Yes | Agent (`true`) | Agent |

---

### 6.2 Tier 1B — Kiosk & POS

#### 3) Kiosk Purchases — `GET /api/Kiosk/GetKioskPurchasedLoyaltyCarddetails`

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `UserId` | Yes | **Hardcoded `4`** | **Login → `operator_id`** |
| `startFrom` | Yes | **Chat** (date range) | Chat |
| `ToEnd` | Yes | **Chat** | Chat |
| `locationName` | No | Chat | Chat / Login locations |
| `IMEI` | No | Chat | Chat |
| `PageNo` / `PageSize` | No* | Agent | Agent |

#### 4) Kiosk Recharges — `GET /api/Kiosk/GetKioskLoyaltyCardRechargedetails`

Same pattern as purchases: `UserId` = Login `operator_id`; dates / location / IMEI from Chat.

#### 5) Remote Device Command — `POST /api/Kiosk/SendCommondToRemoteDevice`

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `operatorId` | Yes | **Hardcoded `4`** | **Login → `operator_id`** |
| `deviceId` | Yes | **Chat** | Chat |
| `command` | Yes | **Chat** (`Reboot` / `Dispense`) | Chat |
| `amount` | Yes | Chat (`>0` for Dispense, `0` for Reboot) | Chat |

#### 6) POS Transactions — `GET /api/POSController/GetPOSTransactionReport`

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `UserId` | Yes | **Hardcoded `4`** | **Login → `operator_id`** |
| `StartDate` | Yes | Chat | Chat |
| `EndDate` | Yes | Chat | Chat |
| `CardCode` | Yes | Chat (required; agent asks if missing) | Chat |
| `Ordertype` | Yes | Chat (required; agent asks if missing) | Chat |
| `AccountType` | Yes | Chat (required; agent asks if missing) | Chat |
| `CardNo` | No | Chat | Chat |
| `LocationId` | No | Chat | Chat / Login default location |
| `POSID` | No | Chat | Chat |

---

### 6.3 Tier 1C — Reports (`get_report` tool)

Common params across most report endpoints:

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `operatorId` | Yes* | **Hardcoded `4`** | **Login → `operator_id`** |
| `locations` | Yes | Agent default `"2"` or Chat | **Login assigned locations** or Chat |
| `fromDate` | Yes | Chat | Chat |
| `toDate` | Yes | Chat | Chat |

\*Except `attendant_detail`, which drops `operatorId` and uses `attendants` when provided.

| Report type | Extra required / notable params | Source |
|-------------|----------------------------------|--------|
| `revenue_by_location` | `isFundUsed` optional | Chat / Agent |
| `revenue_by_position` | `propertyId`, **`propertyValues` (required)**, `isDeletedMachineIncluded`, `isFundUsed` | Chat |
| `revenue_by_machine_type` | `modelId`, `isFundUsed` | Chat / Agent |
| `revenue_by_month` | `isFundUsed` | Chat / Agent |
| `attendant_detail` | `attendants` (attendant user ID) | Chat |
| `promotional_fund` | standard set | Login + Chat |
| `pos_transactions` (reports) | `loyaltyCard` optional | Chat |

---

### 6.4 Tier 1D — Context & config

#### 7) Operator Locations — `GET /api/POSController/GetUserAssignlocations`

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `Passcode` | Yes | **Chat** (agent asks) | **Login (recommended)** |
| `userid` | Yes | **Hardcoded `4`** | **Login → `operator_id`** |

#### 8) Machine Configuration — `GET /api/POSController/GetMachineConfigurations`

| Parameter | Required | Source today | Correct source |
|-----------|----------|--------------|----------------|
| `UserId` | Yes | **Hardcoded `4`** | **Login → `operator_id`** |
| `LocationId` | Yes | **Chat** | Chat / Login default location |
| `MachineInfoId` | No | Chat | Chat |
| `PositionNo` | No | Chat | Chat |
| `BluetoothId` | No | Chat | Chat |

#### 9) Loyalty Card Categories — `GET /api/LoyaltyCard/GetLoyaltyCardSubCategory`

| Parameter | Required | Source |
|-----------|----------|--------|
| *(none)* | — | No login fields needed |

---

### 6.5 Non-Setomatic (no login operator fields)

| Capability | Endpoint / mechanism | Login data needed? |
|------------|----------------------|--------------------|
| Global system status | Scrape `setomaticsystems.com/status` | No |
| Escalation email | Mandrill SMTP | Needs `operator_name/email/phone` from login |
| Escalation SMS | Twilio → on-call number from env | Operator phone useful in email body; SMS goes to `ESCALATION_SMS_TO` |

---

## 7. Minimum vs recommended login payload for frontend

### Minimum (API will accept; escalations will be weak; tools still scope to op `4` today)

```json
{
  "operator_id": 12345,
  "session_id": "<uuid>",
  "message": "..."
}
```

### Recommended production (what you should ship)

```json
{
  "operator_id": 12345,
  "session_id": "<uuid>",
  "message": "...",
  "operator_name": "Jane Operator",
  "operator_email": "jane@laundromat.example",
  "operator_phone": "+15551234567",
  "channel": "chat"
}
```

### Ideal (after small API extension — not implemented yet)

Same as recommended, **plus** store at widget init (for agent/tools later):

```json
{
  "passcode": "3654",
  "default_location_id": 2,
  "location_ids": [2, 5, 8]
}
```

Today those last three are **not** fields on `ChatRequest`. Do not invent them in the client unless the agent API is extended.

---

## 8. Mapping: login fields → Setomatic API params

| Login / chat-context field | Maps to Setomatic param names |
|----------------------------|--------------------------------|
| `operator_id` | `OperatorId`, `LoggedInUserId`, `UserId`, `userid`, `operatorId` |
| `passcode` (future / chat today) | `Passcode` on GetUserAssignlocations |
| Assigned locations (future) | `locations`, `LocationId`, `locationName` filters |
| `operator_name` / `email` / `phone` | Escalation templates only (not Setomatic POS query params) |

---

## 9. Checklist for portal team

**At login / chat open**

- [ ] Read `operator_id` from authenticated portal user
- [ ] Read `operator_name`, `operator_email`, `operator_phone` from profile
- [ ] Generate `session_id` (UUID) once per widget session
- [ ] Keep Setomatic API key / agent `X-API-Key` on **server proxy only**

**On every chat message**

- [ ] Send `operator_id` + `session_id` + `message`
- [ ] Re-send name / email / phone (cheap; keeps escalation context correct)
- [ ] Do **not** rotate `session_id` per message

**Do not send to agent**

- [ ] Portal password / refresh tokens as chat body fields
- [ ] CVV / full payment PAN (PCI — agent will refuse / mask)
- [ ] Expect agent to execute refunds (portal-guided only)

---

## 10. Known gaps to fix in agent code (not frontend blockers)

| Gap | Impact | Owner |
|-----|--------|-------|
| Tools hardcode operator `4` | Wrong-operator data if any ID ≠ 4 is used in prod tools | Agent Phase 1 |
| `passcode` not on `ChatRequest` | Agent asks in chat for location list | Agent + optional portal |
| No `location_ids` on chat request | Reports default `locations="2"` | Agent + portal |
| In-memory sessions (`MemorySaver`) | Lost on agent process restart | Infra / Phase 5 conversation logging |

---

## Related docs

- [API.md](API.md) — full chat REST contract
- [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) — backend API inventory
- [PRD.md](PRD.md) — product requirements including contact fields
- [ENVIRONMENT.md](ENVIRONMENT.md) — `API_KEY`, notification env vars
