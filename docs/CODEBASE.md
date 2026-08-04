# Codebase Map

Every source file in this repo and its role. Use this when navigating without an AI assistant.

**Last verified:** July 2026

---

## Repository layout

```
operator-AI/
├── app.py                      # Streamlit dev UI (in-process graph; persisted routing diagnostics sidebar)
├── pyproject.toml              # Dependencies (uv)
├── .env.example                # Env template — copy to .env
├── README.md                   # Quick start
├── docs/                       # All project documentation
├── KB/                         # Knowledge base source files (PDF/DOCX ingested; .txt skipped)
├── spyderwash_qdrant/          # Generated vector store (gitignored typically)
├── tests/
│   └── test_outage_workflow.py # Outage, post-escalation, follow-up, dedup, greeting reset
└── src/
    ├── config.py               # All env-backed settings
    ├── agent/
    │   ├── graph.py            # LangGraph state machine + workflow guards (start here for behavior)
    │   ├── router.py           # 17-intent semantic classifier + greeting/summary heuristics
    │   ├── nodes.py            # RAG, guardrail, greeting, summary, workflow_reminder, out-of-domain nodes
    │   ├── tools.py            # Setomatic API + status scrape tools
    │   └── state.py            # AgentState TypedDict
    ├── api/
    │   ├── server.py           # Production API :8000
    │   ├── routes.py           # Legacy /query, /notify/* — deprecated
    │   └── schemas.py          # Legacy Pydantic models
    ├── services/
    │   ├── rag_service.py      # Qdrant ingest + RAG chain
    │   └── notifications.py    # Mandrill email + Twilio SMS
    └── utils/
        └── security.py         # mask_credit_cards (PCI)
```

---

## Entry points (what to run)

| Command | File | Purpose |
|---------|------|---------|
| `uv run uvicorn src.api.server:app --port 8000` | server.py | **Canonical** agent API |
| `uv run streamlit run app.py` | app.py | Local demo UI |

---

## Change impact guide

| If you change… | Also run / check… |
|----------------|-------------------|
| `graph.py` | `uv run python -m unittest tests.test_outage_workflow -v` |
| `router.py` | Same tests + manual TC1/TC2 |
| `notifications.py` | Same tests + live escalation smoke |
| `tools.py` | Loyalty/tx/kiosk/POS against live beta API; portal-guided refunds via RAG |
| `rag_service.py` | Run: `uv run python -m data_injection` to re-ingest; test RAG answers |
| `server.py` | curl `/health` and `/api/v1/agent/chat`; CORS for React |
| `KB/` (new docs) | Run: `uv run python -m data_injection` |

---

## Configuration single source

All env vars are read in [src/config.py](../src/config.py) except `OPENAI_API_KEY`, which LangChain reads directly from the process environment (set in `.env` via `load_dotenv()` in server/app).

Full variable list: [ENVIRONMENT.md](ENVIRONMENT.md)

---

## Tests

| File | Coverage |
|------|----------|
| [tests/test_outage_workflow.py](../tests/test_outage_workflow.py) | TC1/TC2, post-escalation, follow-up expansion, blast-radius dedup, greeting reset, notification mock |

**Not covered:** live LLM router, live RAG quality, HTTP integration, Setomatic API, live Twilio/Mandrill.

---

## Legacy / unused surfaces

| Item | Status |
|------|--------|
| `main.py`, `routes.py`, `schemas.py` | **Removed** — legacy code deleted |
| `mock_server.py` | **Removed** — portal-guided refunds (ADR-028); no agent refund execute |

---

## Related documents

- [COMPLETE_DEVELOPER_GUIDE.md](COMPLETE_DEVELOPER_GUIDE.md) — **full** project reference (files, functions, variables, models, APIs, security, setup)
- [CODE_FLOW_AND_FUNCTIONS.md](CODE_FLOW_AND_FUNCTIONS.md) — shorter request flow + function map
- [ONBOARDING.md](ONBOARDING.md) — guided tour for new developers
- [ARCHITECTURE.md](ARCHITECTURE.md) — runtime design
- [API.md](API.md) — REST contract
