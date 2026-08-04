# Setomatic/SpyderWash Operator AI

LangGraph-orchestrated technical support agent for SpyderWash operators: RAG over manuals/Bible, live loyalty/transaction/kiosk/POS/report tools, portal-guided refund help, KB image retrieval, global status checks, and Gregg's troubleshoot-first escalation path.

**Full documentation:** [docs/README.md](docs/README.md)

---

## Architecture (summary)

| Component | Technology |
|-----------|------------|
| Orchestration | LangGraph + MemorySaver ([`src/agent/graph.py`](src/agent/graph.py)) — in-process, not durable |
| Router / tools / RAG LLM | OpenAI or Groq via `LLM_PROVIDER` ([`src/llm.py`](src/llm.py)) — default OpenAI |
| Embeddings | OpenAI `text-embedding-3-small` (1536 dims) |
| Vector store | Qdrant local on-disk (`./spyderwash_qdrant`) — ingest via `uv run python -m data_injection` |
| Retrieval | Hybrid by default (`RAG_RETRIEVAL_METHOD=hybrid`): Qdrant + FlashRank + SQLite co-retrieval |
| Structured KB | SQLite `kb_structured.db` — articles, co-retrieval rules, images |
| Production API | FastAPI [`src/api/server.py`](src/api/server.py) — `POST /api/v1/agent/chat` |
| Dev UI | Streamlit [`app.py`](app.py) — local demo only |
| QA UI | React (dev2) — QA/UAT only, same API |
| Prod UI | .NET Super Admin portal — same API |
| Escalation | Mandrill email + Twilio SMS ([`src/services/notifications.py`](src/services/notifications.py)) |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/TECH_STACK.md](docs/TECH_STACK.md), and [docs/QDRANT_MIGRATION.md](docs/QDRANT_MIGRATION.md).

---

## Prerequisites

- Python >= 3.10 (project developed on 3.14)
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key (embeddings + LLM if `LLM_PROVIDER=openai`)

---

## Setup

```bash
uv sync
# Create .env from your team template (or copy keys from ENVIRONMENT.md)
# At minimum set:
#   OPENAI_API_KEY=
#   SETOMATIC_BASE_URL=
#   API_KEY=
```

All variables: [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)

### Ingest knowledge base (first run / after KB changes)

```bash
uv run python -m data_injection
```

Creates/refreshes `./spyderwash_qdrant/` (collection `spyderwash_docs`). Folder is gitignored.

### KB images — auto on first agent start

Image extraction runs **automatically** the first time you start the API or Streamlit if the `images` table in `kb_structured.db` is empty. On subsequent starts it's a single `COUNT(*)` check — no re-extraction, no OpenAI cost.

Image captions and visual summaries are appended to the RAG context, so answers can reference what screenshots and diagrams show (grounded in caption text — the LLM will not invent UI details).

Force a manual re-extract (e.g. after adding new KB docs):

```bash
uv run python -m src.services.images.pipeline --source all   # or v22 | bible
```

First extract needs Word (Windows) or LibreOffice (Linux/Mac) for DOCX→PDF and OpenAI Vision for captions.

---

## Running locally

### 1. Agent API (required for React / curl integration)

```bash
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
```

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness |
| `POST /api/v1/agent/chat` | Production chat |
| `GET /api/v1/kb/diagnostics` | KB / retrieval diagnostics |
| `GET /api/v1/kb/images/{article_id}` | Images for a case |
| Swagger | `http://localhost:8000/docs` |

### 2. Streamlit demo UI (optional)

```bash
uv run streamlit run app.py
```

Streamlit runs the graph in-process; it does not call `:8000` by default.

Full runbook: [docs/RUNBOOK.md](docs/RUNBOOK.md)

---

## Testing

```bash
uv run python -m unittest tests.test_outage_workflow tests.test_security -v
uv run python -m unittest tests.test_co_retrieval tests.test_image_pipeline tests.test_image_retrieval -v
```

Manual API chat prompts (2 per integrated Setomatic API): [docs/API_TEST_PROMPTS.docx](docs/API_TEST_PROMPTS.docx)

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
| [docs/QDRANT_MIGRATION.md](docs/QDRANT_MIGRATION.md) | Chroma → Qdrant migration notes |
| [docs/BRANDON_KB_ADMIN.md](docs/BRANDON_KB_ADMIN.md) | Brandon mail — KB Admin, chunks, feedback |
| [docs/API.md](docs/API.md) | REST contract for integrators |
| [docs/SETOMATIC_BACKEND_APIS.md](docs/SETOMATIC_BACKEND_APIS.md) | Setomatic backend APIs (tools) |
| [docs/API_TEST_PROMPTS.docx](docs/API_TEST_PROMPTS.docx) | Chat prompts to test each live API |
| [docs/ESCALATION_WORKFLOW.md](docs/ESCALATION_WORKFLOW.md) | Outage workflow (Gregg TC1/TC2) |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | Codebase tour |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design |
| [docs/TESTING.md](docs/TESTING.md) | Test procedures |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operations |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Env vars |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADRs |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | Stack choices |
| [AGENTS.md](AGENTS.md) | Rules for AI coding agents |

---

## Removed / do not use

Legacy `main.py`, `src/api/routes.py`, and `POST /query` have been **deleted**. Use only:

```bash
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
```

ChromaDB is fully removed. Vector store is Qdrant only.

---

## Security

- Credit card masking on API and Streamlit input ([`src/utils/security.py`](src/utils/security.py))
- Hardware status guardrail — no live machine/port telemetry in chat
- Out-of-domain and prompt-injection refusal path
- Refunds: portal guidance only — agent does not execute refunds
