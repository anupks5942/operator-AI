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
  services/
    rag_service.py    — Article-aware v2.2 parser + selective Bible ingest + Qdrant + FlashRank reranking + co-retrieval
    notifications.py  — Twilio SMS + Mandrill email escalation dispatch
  utils/
    security.py  — PCI masking, sanitize_user_text, sanitize_outbound_text
  config.py  — All env var reads (URLs, LLM provider, notification switches)
  llm.py     — create_chat_model() — provider abstraction (OpenAI or Groq)
```

Root files: `app.py` (Streamlit demo with persisted routing diagnostics sidebar).

## Architecture Rules

1. **LangGraph is the orchestrator.** All conversation flow goes through `src/agent/graph.py`. Do not bypass the graph.
2. **Router → Conditional Edge → Node.** The `router` node classifies intent and sets flags; `route_after_classifier()` dispatches to the correct node. Add new intents by extending `IntentClassification` in `router.py` and the edge map in `graph.py`.
3. **Tool node uses ReAct loop** (max 6 iterations). Every AIMessage with tool_calls MUST be followed by ToolMessages. Never single-shot the tool node.
4. **Escalation workflow order:** blast_radius_check → clarify_issue (if vague) → troubleshoot_first → tiered escalation. `entire_location` skips troubleshoot and auto-escalates. `single_machine` failure routes to `confirm_escalation_node` (asks operator permission) before dispatching. This prevents alert fatigue on routine single-machine issues.
5. **`escalation_request` is not an outage intent** (ADR-031). Bare human-request phrases go to `human_escalation_clarify_node` first; they must not enter blast-radius / store-down SMS paths.
6. **RAG-only intents** (`refund_request`, `kiosk_not_responding`, `technical_support`): `api_action_required` must always be `false`. Do NOT route these to the tool node. Outage intents (`machine_down`, `machines_not_starting`, etc.) enter the outage workflow, not direct RAG. Do **not** category-filter `technical_support` to `"No Connection Error"` (ADR-033).
7. **Conversation summary** (`conversation_summary`): honored mid-workflow via early routing; does not reset outage state.
8. **Out-of-domain and PCI guardrails** are static/hardcoded responses — never delegate to LLM or external APIs. Router `_DOMAIN_KEYWORDS` safety net overrides false `out_of_domain`/`greeting` for in-domain terms (printer, portal login, network/IP, cashbox, etc.).
9. **Resolve prompt** (ADR-034/035): append "Did this resolve?" only when the answer has troubleshooting markers (or intent + ≥1 marker); skip on definitional answers and when the RAG answer already asks a follow-up offer.
10. **Post-escalation** (ADR-037): greeting clears routing flags; blast-radius-aware dedup; how-to / new-topic → RAG; only explicit continuations become ticket notes; "no" after "Did this resolve?" can still offer escalate for a *new* issue while an older ticket is open.
11. **NotificationService** uses `USE_LIVE_NOTIFICATIONS` env var. Default `false` = mock/logging only.

## Configuration (src/config.py)
- All URLs, flags, and credentials come from `.env` via `src/config.py`.
- `LLM_PROVIDER`: `"groq"` (default) or `"openai"`. Set in `.env`.
- `RAG_SPARSE_HYBRID_ENABLED`: `false` (default). When `true`, hybrid RAG uses Qdrant-native BM25 sparse + dense RRF fusion instead of dense+SQLite structured. Requires `fastembed` and reingest via `uv run python -m data_injection`.
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
- Ingested into Qdrant at `./spyderwash_qdrant/` with OpenAI `text-embedding-3-small` embeddings (configurable via `OPENAI_EMBEDDING_MODEL` env var). Run `uv run python -m data_injection` after adding new KB files.
- **v2.2 ingestion:** Article-aware parser respects `ARTICLE START`/`ARTICLE END` boundaries. Each article = one atomic chunk with structured metadata (article_id, category, product, intent, search_terms, status, co_retrieval_ids).
- **Bible ingestion:** Selective — troubleshooting Sections 1-14 **plus** operator FAQ from `Operator Portal` through `Voiceover: SpyderWash Troubleshooting Guide` (includes Relay vs Serial Control Board FAQ). Brand wiring, Voiceover transcript, PCI notes, RMA SOP excluded.
- **Retrieval:** MMR k=12, fetch_k=40, lambda=0.5 → FlashRank `ms-marco-TinyBERT-L-2-v2` rerank to top 6 → co-retrieval of mandatory companion articles.
- **Short follow-ups:** Vague affirmatives after a KB reference expand the query from prior AI / `article_id` (ADR-036).
- **System prompt:** v2.2 Section 0 "AI Retrieval and Response Rules" injected into LLM prompt (not stored as chunks).
- Metadata: `article_id`, `category`, `product`, `intent`, `search_terms`, `status`, `source_priority`, `brand`, `doc_type`, `co_retrieval_ids`.

## Testing
- `tests/test_outage_workflow.py` — outage escalation, post-escalation, follow-up expansion, blast-radius dedup, greeting reset
- `tests/test_security.py` — PCI masking and guardrail tests
- Run with: `uv run python -m unittest tests.test_outage_workflow tests.test_security -v`

## Known Gotchas
- `spyderwash_qdrant/` is gitignored — regenerated by `uv run python -m data_injection`.
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
