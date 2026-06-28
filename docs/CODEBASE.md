# Codebase Map

Every source file in this repo and its role. Use this when navigating without an AI assistant.

**Last verified:** June 2026

---

## Repository layout

```
operator-AI/
├── app.py                      # Streamlit dev UI (in-process graph)
├── main.py                     # Legacy FastAPI + console harness — avoid
├── pyproject.toml              # Dependencies (uv)
├── .env.example                # Env template — copy to .env
├── README.md                   # Quick start
├── docs/                       # All project documentation
├── KB/                         # Knowledge base source files (PDF/DOCX ingested; .txt skipped)
├── chroma_db/                  # Generated vector store (gitignored typically)
├── tests/
│   └── test_outage_workflow.py # Primary regression suite (7 tests)
└── src/
    ├── config.py               # All env-backed settings
    ├── agent/
    │   ├── graph.py            # LangGraph state machine (start here for behavior)
    │   ├── router.py           # 15-intent semantic classifier
    │   ├── nodes.py            # RAG, guardrail, out-of-domain nodes
    │   ├── tools.py            # Setomatic API + status scrape tools
    │   └── state.py            # AgentState TypedDict
    ├── api/
    │   ├── server.py           # Production API :8000
    │   ├── mock_server.py      # Mock refunds :8001
    │   ├── routes.py           # Legacy /query, /notify/* — deprecated
    │   └── schemas.py          # Legacy Pydantic models
    ├── services/
    │   ├── rag_service.py      # Chroma ingest + RAG chain
    │   └── notifications.py    # Mandrill email + Twilio SMS
    └── utils/
        └── security.py         # mask_credit_cards (PCI)
```

---

## Entry points (what to run)

| Command | File | Purpose |
|---------|------|---------|
| `uv run uvicorn src.api.server:app --port 8000` | server.py | **Canonical** agent API |
| `uv run uvicorn src.api.mock_server:mock_app --port 8001` | mock_server.py | Mock refunds (when `USE_MOCK_REFUNDS=true`) |
| `uv run streamlit run app.py` | app.py | Local demo UI |
| `uv run python main.py` | main.py | Legacy streaming console test |
| `uv run uvicorn main:app` | main.py | Legacy `/query` API — **do not use** |

---

## Change impact guide

| If you change… | Also run / check… |
|----------------|-------------------|
| `graph.py` | `uv run python -m unittest tests.test_outage_workflow -v` |
| `router.py` | Same tests + manual TC1/TC2 |
| `notifications.py` | Same tests + live escalation smoke |
| `tools.py` | Refund flow with mock :8001; loyalty/tx against beta API |
| `rag_service.py` | Delete `chroma_db/` to re-ingest; test RAG answers |
| `server.py` | curl `/health` and `/api/v1/agent/chat`; CORS for React |
| `KB/` (new docs) | Delete `chroma_db/` and restart |

---

## Configuration single source

All env vars are read in [src/config.py](../src/config.py) except `OPENAI_API_KEY`, which LangChain reads directly from the process environment (set in `.env` via `load_dotenv()` in server/app).

Full variable list: [ENVIRONMENT.md](ENVIRONMENT.md)

---

## Tests

| File | Coverage |
|------|----------|
| [tests/test_outage_workflow.py](../tests/test_outage_workflow.py) | TC1, TC2, post-escalation, helpers, notification mock |

**Not covered:** live LLM router, live RAG quality, HTTP integration, Setomatic API, live Twilio/Mandrill.

---

## Legacy / unused surfaces

| Item | Status |
|------|--------|
| `main.py` `/query` | Deprecated — use `server.py` |
| `routes.py` `/notify/sms`, `/notify/email` | Deprecated — escalation via graph only |
| `mock_server.py` loyalty/transaction endpoints | Present but **not called** by tools.py |

---

## Related documents

- [ONBOARDING.md](ONBOARDING.md) — guided tour for new developers
- [ARCHITECTURE.md](ARCHITECTURE.md) — runtime design
- [API.md](API.md) — REST contract
