# AGENTS.md — Setomatic/SpyderWash Operator AI

## Project Overview
LangGraph-orchestrated technical support agent for SpyderWash laundromat operators. RAG over legacy manuals (PDF/DOCX), live loyalty/transaction API tools, refund workflows, global status checks, and Gregg's troubleshoot-first escalation path. Consumed by a .NET frontend (production), React (QA), and Streamlit (dev demo).

## Key Commands
```bash
uv sync                                  # Install dependencies (uv is the package manager)
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload   # Production API
uv run uvicorn src.api.mock_server:mock_app --port 8001 --reload      # Mock refund backend
uv run streamlit run app.py                                                 # Streamlit dev UI
uv run python -m unittest tests.test_outage_workflow tests.test_security -v  # Run tests
```
No linting or typecheck commands configured. Python 3.14.

## Architecture & Source Layout

```
src/
  agent/
    state.py    — AgentState TypedDict (messages, intent flags, extracted_entities)
    router.py   — semantic_router node: LLM intent classifier + entity extraction
    nodes.py    — RAG, guardrail, greeting, summary, PCI, and out-of-domain nodes
    graph.py    — StateGraph definition, conditional edges, escalation/tool/blast-radius nodes
    tools.py    — LangChain @tool definitions (loyalty, transactions, refund, system status)
  api/
    server.py   — Production FastAPI app: POST /api/v1/agent/chat, GET /health
    routes.py   — Legacy /query endpoint (do NOT extend)
    schemas.py  — Legacy Pydantic schemas
    mock_server.py — Mock refund endpoints on port 8001
  services/
    rag_service.py    — ChromaDB + HuggingFace embeddings + retrieval chain
    notifications.py  — Twilio SMS + Mandrill email escalation dispatch
  utils/
    security.py  — PCI masking, sanitize_user_text, sanitize_outbound_text
  config.py  — All env var reads (URLs, LLM provider, notification switches)
  llm.py     — create_chat_model() — provider abstraction (OpenAI or Groq)
```

Root files: `app.py` (Streamlit demo with persisted routing diagnostics sidebar), `main.py` (multi-turn CLI test script, legacy).

## Architecture Rules

1. **LangGraph is the orchestrator.** All conversation flow goes through `src/agent/graph.py`. Do not bypass the graph.
2. **Router → Conditional Edge → Node.** The `router` node classifies intent and sets flags; `route_after_classifier()` dispatches to the correct node. Add new intents by extending `IntentClassification` in `router.py` and the edge map in `graph.py`.
3. **Tool node uses ReAct loop** (max 6 iterations). Every AIMessage with tool_calls MUST be followed by ToolMessages. Never single-shot the tool node.
4. **Escalation workflow order:** blast_radius_check → clarify_issue (if vague) → troubleshoot_first → escalation (if failed). `entire_location` skips troubleshoot and escalates immediately. This is Gregg's mandated path — do not reorder.
5. **RAG-only intents** (`kiosk_not_responding`, `technical_support`): `api_action_required` must always be `false`. Do NOT route these to the tool node. Outage intents (`machine_down`, `machines_not_starting`, etc.) enter the outage workflow, not direct RAG.
6. **Conversation summary** (`conversation_summary`): honored mid-workflow via early routing; does not reset outage state.
7. **Out-of-domain and PCI guardrails** are static/hardcoded responses — never delegate to LLM or external APIs.
8. **NotificationService** uses `USE_LIVE_NOTIFICATIONS` env var. Default `false` = mock/logging only.

## Configuration (src/config.py)
- All URLs, flags, and credentials come from `.env` via `src/config.py`.
- `LLM_PROVIDER`: `"groq"` (default) or `"openai"`. Set in `.env`.
- `USE_MOCK_REFUNDS`: `"true"` (default) routes refund tools to localhost:8001 mock.
- Loyalty/transaction tools always hit the live Setomatic production API regardless of mock flag.

## State Management
- `MemorySaver` (in-process, not durable). Thread memory keyed by `session_id` / `thread_id`.
- `AgentState` uses `add_messages` reducer for messages and `merge_dicts` for `extracted_entities`.
- Multi-turn entity continuity: turn-2 updates merge on top of turn-1 entities (e.g., card_number persists).

## PCI / Security
- All user text is sanitized via `sanitize_user_text()` before entering the graph.
- CVV/CVC/track data is blocked *before* any LLM call (`contains_prohibited_card_auth_data` in router).
- Outbound text (escalation emails/SMS) is sanitized via `sanitize_outbound_text()`.

## Knowledge Base
- `KB/` contains PDF and DOCX source documents (SpyderWash manuals, troubleshooting guides).
- Ingested into ChromaDB at `./chroma_db/` with HuggingFace `all-MiniLM-L6-v2` embeddings.
- Chunking: 500 chars / 50 overlap. MMR retrieval with k=3, fetch_k=20, lambda=0.6.
- Metadata: `brand`, `doc_type`, `source_file`, `page` enriched per chunk.

## Testing
- `tests/test_outage_workflow.py` — outage escalation workflow tests
- `tests/test_security.py` — PCI masking and guardrail tests
- Run with: `uv run python -m unittest tests.test_outage_workflow tests.test_security -v`

## Known Gotchas
- `main.py` is a legacy entry point. Use `src/api/server.py` for the production API.
- `src/api/routes.py` `/query` endpoint is legacy. Use `POST /api/v1/agent/chat` from `server.py`.
- `chroma_db/` is gitignored — it's regenerated on first run if missing.
- `protobuf<=3.20.3` is pinned due to a LangChain compatibility constraint.
- Transaction history tool has a staging-locked date range (April 2026) — switch to rolling 6-month window before production (agent-side fix, not a backend API).
- `get_transaction_history` pre-validates cards via balance API; supports `count` (1–20) and `include_refunds` → API `isRefund`.
- Card numbers are normalized (LC- prefix stripped) in loyalty/transaction tools.
- The `__init__.py` files are missing from most packages; imports work because `src/` is on `sys.path` implicitly. Add `__init__.py` files if restructuring to a proper package layout.

## Documentation
Full docs in `docs/`. Key files for agents making changes:
- `docs/ARCHITECTURE.md` — system design
- `docs/ESCALATION_WORKFLOW.md` — Gregg's outage workflow (TC1/TC2)
- `docs/INTENT_MATRIX.md` — Brandon matrix → router intent mapping
- `docs/SETOMATIC_BACKEND_APIS.md` — final Setomatic POS API scope: 7 APIs (4 core + 3 future platform)
- `docs/ENVIRONMENT.md` — all env var descriptions
- `docs/API.md` — REST contract for integrators
- `docs/DECISIONS.md` — architectural decision records
