# AGENTS.md — Setomatic/SpyderWash Operator AI

## Project Overview
LangGraph-orchestrated technical support agent for SpyderWash laundromat operators. RAG over manuals/Bible (PDF/DOCX/TXT), live loyalty/transaction/kiosk/POS tools, portal-guided refund help (no agent-executed refunds), global status checks, and Gregg's troubleshoot-first escalation path. Consumed by a .NET frontend (production), React (QA), and Streamlit (dev demo).

## Key Commands
```bash
uv sync                                  # Install dependencies (uv is the package manager)
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload   # Production API
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
    tools.py    — LangChain @tool definitions (loyalty, transactions, system status, kiosk purchases/recharges, POS transactions, remote device commands)
  api/
    server.py   — Production FastAPI app: POST /api/v1/agent/chat, GET /health
    routes.py   — Legacy /query endpoint (do NOT extend)
    schemas.py  — Legacy Pydantic schemas
  services/
    rag_service.py    — Article-aware v2.2 parser + selective Bible ingest + ChromaDB + FlashRank reranking + co-retrieval
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
4. **Escalation workflow order:** blast_radius_check → clarify_issue (if vague) → troubleshoot_first → tiered escalation. `entire_location` skips troubleshoot and auto-escalates. `single_machine` failure routes to `confirm_escalation_node` (asks operator permission) before dispatching. This prevents alert fatigue on routine single-machine issues.
5. **RAG-only intents** (`refund_request`, `kiosk_not_responding`, `technical_support`): `api_action_required` must always be `false`. Do NOT route these to the tool node. Outage intents (`machine_down`, `machines_not_starting`, etc.) enter the outage workflow, not direct RAG.
6. **Conversation summary** (`conversation_summary`): honored mid-workflow via early routing; does not reset outage state.
7. **Out-of-domain and PCI guardrails** are static/hardcoded responses — never delegate to LLM or external APIs.
8. **NotificationService** uses `USE_LIVE_NOTIFICATIONS` env var. Default `false` = mock/logging only.

## Configuration (src/config.py)
- All URLs, flags, and credentials come from `.env` via `src/config.py`.
- `LLM_PROVIDER`: `"groq"` (default) or `"openai"`. Set in `.env`.
- **Refunds:** portal guidance only (ADR-028). No mock refund server; no agent-executed refund tools. Bible owns refund how-to content.
- Loyalty/transaction/kiosk/POS tools always hit the live Setomatic API.

## State Management
- `MemorySaver` (in-process, not durable). Thread memory keyed by `session_id` / `thread_id`.
- `AgentState` uses `add_messages` reducer for messages and `merge_dicts` for `extracted_entities`.
- Multi-turn entity continuity: turn-2 updates merge on top of turn-1 entities (e.g., card_number persists).

## PCI / Security
- All user text is sanitized via `sanitize_user_text()` before entering the graph.
- CVV/CVC/track data is blocked *before* any LLM call (`contains_prohibited_card_auth_data` in router).
- Outbound text (escalation emails/SMS) is sanitized via `sanitize_outbound_text()`.

## Knowledge Base
- `KB/` contains the two active KB documents: **v2.2** (171 structured articles for AI) and **Setomatic Bible** (raw troubleshooting source). v1.8 is superseded.
- Ingested into ChromaDB at `./chroma_db/` with OpenAI `text-embedding-3-small` embeddings (configurable via `OPENAI_EMBEDDING_MODEL` env var). Delete `chroma_db/` and restart the app after adding new KB files.
- **v2.2 ingestion:** Article-aware parser respects `ARTICLE START`/`ARTICLE END` boundaries. Each article = one atomic chunk with structured metadata (article_id, category, product, intent, search_terms, status, co_retrieval_ids).
- **Bible ingestion:** Selective — only Sections 1-14 (troubleshooting). Installation/wiring content (82.5% of doc) excluded per v2.2 rules.
- **Retrieval:** MMR k=8, fetch_k=30, lambda=0.5 → FlashRank rerank to top 4 → co-retrieval of mandatory companion articles.
- **System prompt:** v2.2 Section 0 "AI Retrieval and Response Rules" injected into LLM prompt (not stored as chunks).
- Metadata: `article_id`, `category`, `product`, `intent`, `search_terms`, `status`, `source_priority`, `brand`, `doc_type`, `co_retrieval_ids`.

## Testing
- `tests/test_outage_workflow.py` — outage escalation workflow tests
- `tests/test_security.py` — PCI masking and guardrail tests
- Run with: `uv run python -m unittest tests.test_outage_workflow tests.test_security -v`

## Known Gotchas
- `main.py` is a legacy entry point. Use `src/api/server.py` for the production API.
- `src/api/routes.py` `/query` endpoint is legacy. Use `POST /api/v1/agent/chat` from `server.py`.
- `chroma_db/` is gitignored — it's regenerated on first run if missing.
- `protobuf<=3.20.3` is pinned due to a LangChain compatibility constraint.
- `get_transaction_history` pre-validates cards via balance API; supports `count` (1–20), `include_refunds` → API `isRefund`, and optional `start_date`/`end_date` (YYYY-MM-DD). Defaults to a rolling 6-month window when dates are omitted.
- All transaction tools (loyalty, kiosk purchases/recharges, POS) default to **5 records per page**. Pagination is client-side (kiosk/POS APIs return all data at once; agent slices locally via `page_no`). "Show more" triggers the router's pre-LLM regex heuristic (`Showing \d+ of \d+ records`) → stays in API intent → tool re-called with `page_no` incremented. Transaction IDs are hidden from operator display but kept internally for refund flow.
- Card numbers are normalized (LC- prefix stripped) in loyalty/transaction tools.
- The `__init__.py` files are missing from most packages; imports work because `src/` is on `sys.path` implicitly. Add `__init__.py` files if restructuring to a proper package layout.

## Documentation
Full docs in `docs/`. Key files for agents making changes:
- `docs/ARCHITECTURE.md` — system design
- `docs/ESCALATION_WORKFLOW.md` — Gregg's outage workflow (TC1/TC2)
- `docs/INTENT_MATRIX.md` — Brandon matrix → router intent mapping
- `docs/SETOMATIC_BACKEND_APIS.md` — Setomatic API scope: balance + transactions + kiosk/POS; refunds = portal guidance (no agent execute)
- `docs/ENVIRONMENT.md` — all env var descriptions
- `docs/API.md` — REST contract for integrators
- `docs/DECISIONS.md` — architectural decision records
