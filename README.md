# Setomatic/SpyderWash Operator AI

LangGraph-orchestrated technical support agent for SpyderWash operators: RAG over legacy manuals, live loyalty/transaction tools, refund workflows, global status checks, and Gregg's troubleshoot-first escalation path.

**Full documentation:** [docs/README.md](docs/README.md)

---

## Architecture (summary)

| Component | Technology |
|-----------|------------|
| Orchestration | LangGraph + MemorySaver ([`src/agent/graph.py`](src/agent/graph.py)) — in-process, not durable |
| Router / tools / RAG LLM | OpenAI (`gpt-4o-mini` default) |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` |
| Vector store | ChromaDB (`./chroma_db`) — ingests PDF/DOCX from `KB/`; SpyderWash Bible target — see [docs/KB_AND_PLATFORM.md](docs/KB_AND_PLATFORM.md) |
| Production API | FastAPI [`src/api/server.py`](src/api/server.py) — `POST /api/v1/agent/chat` |
| Dev UI | Streamlit [`app.py`](app.py) — local demo only |
| QA UI | React (dev2) — QA/UAT only, same API |
| Prod UI | .NET Super Admin portal — planned, same API |
| Escalation | Mandrill email + Twilio SMS ([`src/services/notifications.py`](src/services/notifications.py)) |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/TECH_STACK.md](docs/TECH_STACK.md).

---

## Prerequisites

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/) package manager

---

## Setup

```bash
uv sync
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY=
```

All variables: [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)

---

## Running locally

### 1. Agent API (required for React / curl integration)

```bash
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
```

- Health: `GET http://localhost:8000/health`
- Chat: `POST http://localhost:8000/api/v1/agent/chat`
- Swagger: `http://localhost:8000/docs`

### 2. Mock refund backend (optional — default ON)

```bash
uv run uvicorn src.api.mock_server:mock_app --port 8001 --reload
```

Required when `USE_MOCK_REFUNDS=true` (default). Loyalty/transactions use live Setomatic API regardless.

### 3. Streamlit demo UI (optional)

```bash
uv run streamlit run app.py
```

Streamlit runs the graph in-process; it does not call `:8000` by default.

Full runbook: [docs/RUNBOOK.md](docs/RUNBOOK.md)

---

## Testing

```bash
uv run python -m unittest tests.test_outage_workflow tests.test_security -v
```

Manual TC1/TC2: [docs/TESTING.md](docs/TESTING.md)

---

## Documentation index

| Doc | Purpose |
|-----|---------|
| [docs/README.md](docs/README.md) | Documentation hub — start here |
| [docs/CODEBASE.md](docs/CODEBASE.md) | Repo file map |
| [docs/PRD.md](docs/PRD.md) | Product requirements |
| [docs/REQUIREMENTS_MAP.md](docs/REQUIREMENTS_MAP.md) | Vendor requirements traceability |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phased backlog to production |
| [docs/INTENT_MATRIX.md](docs/INTENT_MATRIX.md) | Brandon matrix → router intents |
| [docs/KB_AND_PLATFORM.md](docs/KB_AND_PLATFORM.md) | Bible, images, videos, Rackspace strategy |
| [docs/BRANDON_KB_ADMIN.md](docs/BRANDON_KB_ADMIN.md) | Brandon mail — KB Admin, chunks, feedback |
| [docs/API.md](docs/API.md) | REST contract for integrators |
| [docs/SETOMATIC_BACKEND_APIS.md](docs/SETOMATIC_BACKEND_APIS.md) | Setomatic backend APIs (tools) |
| [docs/ESCALATION_WORKFLOW.md](docs/ESCALATION_WORKFLOW.md) | Outage workflow (Gregg TC1/TC2) |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | Codebase tour |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design |
| [docs/TESTING.md](docs/TESTING.md) | Test procedures |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operations |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Env vars |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADRs |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | Stack choices |

---

## Legacy (do not use for new integrations)

- `uv run uvicorn main:app` — old `/query` API; use `server.py`
- `POST /query` — replaced by `/api/v1/agent/chat`

---

## Security

- Credit card masking on API and Streamlit input ([`src/utils/security.py`](src/utils/security.py))
- Hardware status guardrail — no live machine/port telemetry in chat
- Out-of-domain and prompt-injection refusal path
