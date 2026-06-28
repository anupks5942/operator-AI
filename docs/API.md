# API Reference — Production Agent

**Canonical server:** [src/api/server.py](../src/api/server.py) (FastAPI v1.0.0)  
**Base URL (local):** `http://localhost:8000`  
**OpenAPI / Swagger:** `http://localhost:8000/docs`

Legacy endpoints in [main.py](../main.py) and [routes.py](../src/api/routes.py) are **deprecated** for new integrations.

---

## POST /api/v1/agent/chat

Run one conversation turn through the LangGraph agent. Multi-turn chat uses the same `session_id` on every request.

### Request

**Content-Type:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `operator_id` | integer | Yes | Operator account ID. Stored in agent state for escalation display. **Setomatic tool calls still use hardcoded `OperatorId=4` until Phase 1** — see [ROADMAP.md](ROADMAP.md) |
| `session_id` | string | Yes | Stable session ID for conversation memory (maps to LangGraph `thread_id`) |
| `message` | string | Yes | Operator plain-text message |
| `operator_name` | string | No | Display name for escalation email |
| `operator_email` | string | No | Email for escalation template |
| `operator_phone` | string | No | Phone for escalation template |

Credit card numbers in `message` are masked via [sanitize_user_text](../src/utils/security.py) before processing. CVV/track data requests receive a static PCI refusal.

### Response (200)

| Field | Type | Description |
|-------|------|-------------|
| `reply` | string | Final assistant text for this turn |
| `detected_intent` | string | Router intent label (e.g. `machines_not_starting`) |
| `requires_escalation` | boolean | `true` if `escalation_node` dispatched email and/or SMS **this turn** (`escalation_dispatched` in state) |

### Errors

| Status | Cause |
|--------|-------|
| 422 | Invalid request body (Pydantic validation) |
| 500 | Graph execution failed (`detail` contains exception message) |

### Example — first message

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": 4,
    "session_id": "demo-session-001",
    "message": "My washer won'\''t start.",
    "operator_name": "Jane Operator",
    "operator_email": "jane@example.com",
    "operator_phone": "+15551234567"
  }'
```

Example response:

```json
{
  "reply": "To help me get you the right fix, is this affecting just one specific machine, or is your entire laundromat offline?",
  "detected_intent": "machines_not_starting",
  "requires_escalation": false
}
```

### Example — follow-up (same session)

Use the **same** `session_id`:

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": 4,
    "session_id": "demo-session-001",
    "message": "Just one machine.",
    "operator_name": "Jane Operator",
    "operator_email": "jane@example.com",
    "operator_phone": "+15551234567"
  }'
```

### Integration notes for .NET / React

1. Generate one `session_id` per chat widget session (UUID recommended).
2. Pass authenticated operator profile fields when available — Streamlit omits them today, so escalation emails may show "Unknown Operator".
3. Display `reply` to the user; use `requires_escalation` for UI badges or analytics.
4. Do **not** create a new `session_id` per message — that breaks multi-turn workflows (blast-radius, refunds).
5. `.NET` may proxy to this API server-side to avoid exposing keys; CORS is configured for browser clients.

---

## GET /health

Liveness probe for load balancers and local checks.

```bash
curl -s http://localhost:8000/health
```

Response:

```json
{
  "status": "healthy",
  "service": "setomatic-operator-ai"
}
```

---

## CORS

Allowed origins (browser clients):

- `https://beta.spyderwash.com`
- `https://www.spyderwash.com`
- `http://localhost:3000` (React dev)
- `http://localhost:5000`
- `http://localhost:8080`

Methods: `GET`, `POST`, `OPTIONS`  
Credentials: allowed

To add a QA origin, update `allow_origins` in [server.py](../src/api/server.py).

---

## Telemetry

Requests to `/api/v1/agent/chat` log structured lines with correlation ID, latency, and outcome. Slow requests over 10 seconds emit a WARNING.

Logger name: `setomatic.api`

---

## Legacy endpoints (do not use)

| Endpoint | Server | Replacement |
|----------|--------|-------------|
| `POST /query` | main.py | `POST /api/v1/agent/chat` |
| `GET /health` | main.py routes | `GET /health` on server.py |
| `POST /notify/sms` | routes.py | Escalation via graph only |
| `POST /notify/email` | routes.py | Escalation via graph only |

Legacy `/query` does not support `operator_id`, `session_id`, or structured escalation flags.

---

## Related documents

- [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) — Setomatic POS APIs the agent calls
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) — multi-turn behavior
- [ENVIRONMENT.md](ENVIRONMENT.md) — configuration
- [TESTING.md](TESTING.md) — verification
