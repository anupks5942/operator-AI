# Runbook

Operational guide for local development, QA, and client demos.

---

## Local development — full stack

Open terminals from the repo root.

### Terminal 1 — Mock refund backend (optional)

Required when `USE_MOCK_REFUNDS=true` (default).

```bash
uv run uvicorn src.api.mock_server:mock_app --port 8001 --reload
```

Swagger: `http://localhost:8001/docs`

Active mock endpoints used by tools: `RefundEligibility`, `RefundProcessing`. Loyalty/transaction mock routes exist but are **not** wired to tools.

### Terminal 2 — Agent API (required for React / curl)

```bash
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
```

- Health: `GET http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`
- Chat: `POST http://localhost:8000/api/v1/agent/chat`

### Terminal 3 — Streamlit demo (optional)

```bash
uv run streamlit run app.py
```

Default: `http://localhost:8501` — in-process graph; does not require Terminal 2.

---

## Minimal setups

| Goal | Processes |
|------|-----------|
| Unit tests | None — `uv run python -m unittest tests.test_outage_workflow -v` |
| Streamlit (RAG + outage) | Terminal 3 + `OPENAI_API_KEY` |
| React QA | Terminal 2 + React app |
| Refund dev | Terminals 1 + 2 |
| Live escalation | Terminal 2 or 3 + `USE_LIVE_NOTIFICATIONS=true` |

---

## First-time setup

```bash
uv sync
cp .env.example .env
# Minimum: OPENAI_API_KEY=sk-...
```

See [ENVIRONMENT.md](ENVIRONMENT.md) for all variables.

---

## Environment matrix

| Environment | Agent API | Refunds | Notifications |
|-------------|-----------|---------|---------------|
| Local dev | `http://localhost:8000` | Mock `:8001` (default) | Usually mock |
| QA React (dev2) | `:8000` or deployed | Mock until beta ready | Test recipients |
| UAT | Deployed (infra vendor) | Live when unblocked | Client test |
| Production | Deployed (infra vendor / Rackspace) | Live Setomatic | Client prod |

Production hosting not in this repo — [ROADMAP.md](ROADMAP.md) Phase 3; Rackspace preferred — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).

---

## Health checks

```bash
curl -s http://localhost:8000/health
```

Expected:

```json
{"status":"healthy","service":"setomatic-operator-ai"}
```

---

## Demo-day checklist

1. Escalation recipients in `.env`:
   - `ESCALATION_EMAIL=support@setomaticsystems.com`
   - `ESCALATION_SMS_TO=+12517538447` (confirm with client)
2. `USE_LIVE_NOTIFICATIONS=true`
3. Run [TESTING.md](TESTING.md) automated tests
4. Start agent API (Terminal 2)
5. Confirm React QA base URL → `:8000`
6. Dry-run TC1 + TC2 on demo UI
7. OpenAI credits available

---

## Common failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| 500 on chat | Missing `OPENAI_API_KEY` | Set in `.env`, restart |
| Empty RAG answers | Empty/missing `chroma_db/` | Add PDF/DOCX to `KB/`, delete `chroma_db/`, restart |
| KB txt not in answers | `.txt` not ingested | Use PDF/DOCX or extend rag_service loader |
| Refund tool errors | Mock not running | Start `:8001` or `USE_MOCK_REFUNDS=false` when APIs ready |
| No email/SMS | `USE_LIVE_NOTIFICATIONS=false` | Set `true` + Twilio/SMTP vars |
| Email/SMS failed | Bad credentials | Check server logs |
| CORS error | Origin not allowed | Add origin in [server.py](../src/api/server.py) |
| TC2 skips troubleshoot | Stale Streamlit session | Fresh session or use automated tests |
| "Unknown Operator" in email | Contact fields omitted | Pass via API ([API.md](API.md)) |

---

## Knowledge base re-ingest

Chroma builds on first `RAGService()` init when `chroma_db/` is empty.

To force rebuild:

1. Stop processes
2. Delete `chroma_db/`
3. Restart — ingests `.pdf` and `.docx` from `KB/` only

Chunk settings: 500 chars, 50 overlap ([rag_service.py](../src/services/rag_service.py)).

---

## Legacy commands (avoid)

```bash
uv run uvicorn main:app --reload   # use server.py
uv run python main.py              # console harness only
```

---

## Related documents

- [ENVIRONMENT.md](ENVIRONMENT.md) — configuration
- [TESTING.md](TESTING.md) — verification
- [API.md](API.md) — integration contract
- [CODEBASE.md](CODEBASE.md) — file map
