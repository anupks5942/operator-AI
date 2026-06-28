# Technology Stack

Current MVP choices (as implemented in this repo) vs target production stack. See [DECISIONS.md](DECISIONS.md) for rationale.

---

## Current stack (MVP)

| Layer | Technology | Version / default | Notes |
|-------|------------|-------------------|-------|
| Language | Python | >= 3.10 | [pyproject.toml](../pyproject.toml) |
| Package manager | uv | — | `uv sync` to install |
| Web framework | FastAPI | >= 0.100 | Production API |
| Dev UI | Streamlit | >= 1.57 | Local demo only; in-process graph |
| Orchestration | LangGraph | >= 0.0.1 | State machine + routing |
| Session memory | LangGraph MemorySaver | In-process | **Not durable** — lost on restart; no SQLite/Redis yet |
| Router LLM | OpenAI | `gpt-4o-mini` default | [ROUTER_OPENAI_MODEL](../src/config.py) |
| Tool-calling LLM | OpenAI | `gpt-4o-mini` default | [TOOL_OPENAI_MODEL](../src/config.py) |
| RAG LLM | OpenAI | `gpt-4o-mini` default | [RAG_OPENAI_MODEL](../src/config.py) via `ChatOpenAI` |
| Embeddings | HuggingFace | `all-MiniLM-L6-v2` | Local sentence-transformers |
| Vector store | ChromaDB | `./chroma_db` | Single-node persistence |
| Document loaders | LangChain | PDF, DOCX only | `.txt` in `KB/` not ingested — [rag_service.py](../src/services/rag_service.py). Bible ~500 pp; structured chunks Phase 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| HTTP client | requests | >= 2.31 | Setomatic API + status scrape |
| Escalation email | Mandrill SMTP | smtp.mandrillapp.com:587 | Feature-flagged |
| Escalation SMS | Twilio | >= 9.0 | Feature-flagged |
| PCI masking | Custom | [security.py](../src/utils/security.py) | Credit card redaction on API input |

### Runtime processes (local dev)

| Process | Port | File |
|---------|------|------|
| Agent API (canonical) | 8000 | [src/api/server.py](../src/api/server.py) |
| Mock refund backend | 8001 | [src/api/mock_server.py](../src/api/mock_server.py) — refund tools only |
| Streamlit UI | 8501 (default) | [app.py](../app.py) |

### Frontends

| UI | Role | Integration |
|----|------|-------------|
| Streamlit | Developer demo only | Imports `agent_app` directly (no HTTP) |
| React chatbot | **QA / UAT only** (dev2) | HTTP → `:8000/api/v1/agent/chat` |
| .NET Super Admin widget | **Production** (Setomatic) | HTTP → `:8000/api/v1/agent/chat` |

### Legacy (do not use for new work)

| Surface | File | Replacement |
|---------|------|-------------|
| `POST /query` | [main.py](../main.py) + [routes.py](../src/api/routes.py) | `POST /api/v1/agent/chat` |
| `POST /notify/sms` | [routes.py](../src/api/routes.py) | Escalation via graph only |

---

## Target production stack (planned)

These are **documented targets**, not yet implemented. Details in [ROADMAP.md](ROADMAP.md) Phase 2–3.

| Layer | Target | Why |
|-------|--------|-----|
| Hosting | **Rackspace** (preferred) — containers alongside SpyderWash FE/BE; Azure fallback if required | **infra vendor** Phase 3 — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| KB assets | Rackspace Cloud Files (Bible PDF + operator videos) | Ingest pipeline → shared vector index |
| Secrets | Key Vault / injected env | No committed `.env` in prod |
| Vector DB | Qdrant Cloud (or equivalent) | Multi-replica API, shared KB |
| Checkpoints | PostgreSQL or Redis | Replace in-memory MemorySaver at scale |
| Observability | APM + log aggregation | Extend existing structured logs in server.py |
| CI | GitHub Actions (or Azure DevOps) | Run `tests/test_outage_workflow.py` on PR |
| Auth | API key or JWT from .NET gateway | Not on agent API today |
| Streamlit | Removed from prod | Dev-only tool |

---

## External dependencies

| Service | Purpose | Config |
|---------|---------|--------|
| OpenAI API | Router, tools, RAG | `OPENAI_API_KEY` |
| Setomatic beta API | Loyalty, transactions, refunds | `SETOMATIC_BASE_URL` |
| Mandrill | Escalation email | SMTP vars in [ENVIRONMENT.md](ENVIRONMENT.md) |
| Twilio | Escalation SMS | Twilio vars in [ENVIRONMENT.md](ENVIRONMENT.md) |
| setomaticsystems.com/status | Global outage check | Scraped by tool (no API key) |

---

## Explicit non-goals (v1 prod)

- Customer Agent
- Live hardware telemetry API
- Twilio Media Streams voice (until Phase 4)
- Video transcription / multimodal RAG (until product chooses strategy — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md))

- Groq as RAG provider (code uses OpenAI; Groq key not required today)

---

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — how components connect
- [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) — Bible, videos, Rackspace
- [ENVIRONMENT.md](ENVIRONMENT.md) — all env vars
- [DECISIONS.md](DECISIONS.md) — ADRs
