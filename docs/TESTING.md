# Testing Guide

Verify Operator Agent behavior before demos, PRs, and releases.

---

## Automated tests

### Outage workflow (TC1 / TC2)

Deterministic — mocks router and RAG; **no API keys required**.

```bash
uv run python -m unittest tests.test_outage_workflow tests.test_security -v
```

**File:** [tests/test_outage_workflow.py](../tests/test_outage_workflow.py)

| Test | What it covers |
|------|----------------|
| `OutageWorkflowTests.test_tc1_happy_path_no_escalation` | Blast-radius → troubleshoot → resolved; zero escalations |
| `OutageWorkflowTests.test_tc2_troubleshoot_then_escalate_same_session` | TC1 then store-down → escalate; correct summary |
| `OutageWorkflowTests.test_post_escalation_followups` | No blast-radius restart after ticket |
| `OutageHelperTests.test_infer_blast_radius_entire_location` | Router heuristic |
| `OutageHelperTests.test_escalation_context_uses_current_incident` | Summary from current outage |
| `OutageHelperTests.test_format_conversation_for_email` | Email transcript formatting |
| `NotificationServiceTests.test_send_escalation_mock_mode` | Mock-mode send_escalation |

**Run before changes to:** `graph.py`, `router.py`, `notifications.py`, `security.py`

### PCI compliance checks

Manual smoke (after security changes):

1. Send `My card is 4111111111111111` via API or Streamlit → reply/transcript shows `**-**-****-1111` only.
2. Send `My CVV is 123` → static PCI refusal (no LLM answer about CVV).
3. Run automated PCI tests:

```bash
uv run python -m unittest tests.test_security -v
```

Automated: [tests/test_security.py](../tests/test_security.py) — PAN masking, CVV detection, graph PCI routing.

---

## Manual smoke tests

### Prerequisites

```bash
uv sync
cp .env.example .env
# OPENAI_API_KEY required for manual chat tests
```

```bash
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
```

Optional mock refunds:

```bash
uv run uvicorn src.api.mock_server:mock_app --port 8001 --reload
```

### Streamlit TC1 / TC2

```bash
uv run streamlit run app.py
```

Use a **fresh browser session** for isolated TC2 testing.

**TC1:**

1. "My washer won't start."
2. "Just one machine."
3. "Yes, that fixed it."

Expect: blast-radius → KB steps → polite close. No ticket.

**TC2 (same session after TC1):**

4. "Everything is down at the Chetu Test Location!"
5. "No, I checked the gateway and it's still completely offline."

Expect: troubleshoot → ticket `TKT-...`. With live notifications, email + SMS arrive.

Detail: [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md)

### API curl TC1

**Linux / macOS / Git Bash:**

```bash
SESSION="api-test-$(uuidgen 2>/dev/null || echo manual-001)"

curl -s -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d "{\"operator_id\":4,\"session_id\":\"$SESSION\",\"message\":\"My washer won't start.\"}"

curl -s -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d "{\"operator_id\":4,\"session_id\":\"$SESSION\",\"message\":\"Just one machine.\"}"

curl -s -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d "{\"operator_id\":4,\"session_id\":\"$SESSION\",\"message\":\"Yes, that fixed it.\"}"
```

**PowerShell (Windows):**

```powershell
$SESSION = "api-test-" + [guid]::NewGuid().ToString()
$body1 = @{ operator_id=4; session_id=$SESSION; message="My washer won't start." } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/v1/agent/chat -ContentType "application/json" -Body $body1
# Repeat with same $SESSION for turns 2 and 3
```

Check `requires_escalation` is `false` on all turns.

### Live escalation smoke (optional)

Personal recipients in `.env`, revert before client demo:

```env
USE_LIVE_NOTIFICATIONS=true
ESCALATION_EMAIL=your-email@example.com
ESCALATION_SMS_TO=+1XXXXXXXXXX
```

Run TC2 turn 5 in a session that completed troubleshoot.

---

## Other manual checks

| Scenario | Input | Expected |
|----------|-------|----------|
| Hardware guardrail | "Is port 4 offline right now?" | Refusal; portal redirect |
| Out of domain | "What's the weather?" | Static refusal |
| Loyalty balance | "Balance on card 501896" | Tool call (live API) |
| System status | "Is SpyderWash down globally?" | Status scrape tool |

---

## Pre-demo checklist

- [ ] `uv run python -m unittest tests.test_outage_workflow -v` — all pass
- [ ] TC1 + TC2 on target UI (Streamlit or React QA)
- [ ] `ESCALATION_EMAIL` / `ESCALATION_SMS_TO` → **client** addresses
- [ ] `USE_LIVE_NOTIFICATIONS=true` for live demo
- [ ] Agent API on `:8000`
- [ ] React QA points to correct API URL
- [ ] Valid `OPENAI_API_KEY`

---

## Not covered by automated tests

- Live LLM router (mocked in tests)
- Live RAG answer quality (mocked)
- Setomatic API integration
- Live Twilio/Mandrill delivery
- HTTP FastAPI integration (Phase 1)

---

## Legacy test files (do not exist)

Do not reference: `test_graph.py`, `test_router_context.py`, `test_rag.py`, `test_server.py`, `test.py`, `KB_VERIFICATION_QA.md`.

Primary suite: [tests/test_outage_workflow.py](../tests/test_outage_workflow.py)

---

## Related documents

- [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md)
- [RUNBOOK.md](RUNBOOK.md)
- [ROADMAP.md](ROADMAP.md)
