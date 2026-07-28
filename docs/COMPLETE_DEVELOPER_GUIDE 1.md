# SpyderWash Operator AI — Complete Developer Guide

**Purpose:** A new developer should be able to understand architecture, code flow, every important function/variable, models, APIs, security, setup, and limitations **without asking the original author**.

**Verified against source:** July 2026  
**Canonical entrypoints:** `src/api/server.py` (prod API), `app.py` (Streamlit demo)  
**Companion short map:** [CODE_FLOW_AND_FUNCTIONS.md](CODE_FLOW_AND_FUNCTIONS.md)

> **Honesty check:** This repo has ~5,000+ lines of Python. Documenting every literal source line is noise. This guide documents **every file, class, function, important constant/variable, model, dependency, and flow** with purpose, inputs, outputs, callers, and impact. That is what “full detail without the original developer” actually means.

---

# Part A — Project overview

## A.1 What this system does

LangGraph-orchestrated **technical support agent** for SpyderWash laundromat operators:

| Capability | Implementation |
|---|---|
| Knowledge answers / troubleshooting | RAG over KB (v2.2 articles + selective Bible) via ChromaDB + FlashRank |
| Live loyalty / transactions / kiosk / POS / reports / remote device | LangChain `@tool` → HTTP to Setomatic beta API |
| Refunds | **Portal guidance only** (RAG). No agent-executed refund API |
| Outages | Blast-radius → clarify → troubleshoot → confirm → escalate (email/SMS) |
| Guardrails | PCI (CVV/track), out-of-domain, no live hardware telemetry |

## A.2 Who calls it

| Consumer | Integration |
|---|---|
| .NET Super Admin (production target) | `POST /api/v1/agent/chat` |
| React QA chatbot | Same HTTP API |
| Streamlit (`app.py`) | In-process `agent_app` (no HTTP) |

## A.3 High-level request flow

```
Operator message
    → sanitize_user_text (mask PAN)
    → LangGraph MemorySaver (thread_id = session_id)
    → semantic_router (classify intent + entities)
    → route_after_classifier (pick ONE node)
    → node executes (RAG / tools / escalation / static reply)
    → END
    → reply + detected_intent + requires_escalation
```

Almost every turn is **one router pass → one action node → END**.  
Exceptions: `rag_agent` may continue via `route_after_rag`; `tool_node` runs an internal ReAct loop; `new_issue_after_escalation` has a conditional chain.

---

# Part B — Folder structure & file responsibility

```
operator-AI/
├── app.py                          # Streamlit demo UI (in-process graph)
├── main.py                         # LEGACY CLI / old FastAPI — do not use for prod
├── pyproject.toml                  # Dependencies (uv)
├── AGENTS.md                       # Rules for AI coding agents working on this repo
├── README.md                       # Quick start
├── KB/                             # Source manuals (DOCX/PDF) ingested into Chroma
├── chroma_db/                      # Generated vector DB (local disk; usually gitignored)
├── flashrank_cache/                # Cached FlashRank ONNX model files
├── tests/
│   ├── test_outage_workflow.py     # Outage / post-escalation / dedup / greeting reset
│   ├── test_security.py            # PCI masking / CVV detection
│   └── test_bug_fixes.py           # Regression cases
├── docs/                           # All documentation (this file lives here)
└── src/
    ├── config.py                   # SINGLE source of env-backed settings
    ├── llm.py                      # OpenAI / Groq chat model factory
    ├── agent/
    │   ├── state.py                # AgentState TypedDict + merge_dicts reducer
    │   ├── router.py               # Intent classifier (graph entry node)
    │   ├── nodes.py                # RAG, greeting, PCI, OOD, summary, reminder
    │   ├── graph.py                # Graph wiring, outage nodes, tool_node, routing
    │   └── tools.py                # Setomatic @tool wrappers
    ├── api/
    │   ├── server.py               # Production FastAPI
    │   ├── routes.py               # LEGACY /query + /notify — do not extend
    │   └── schemas.py              # LEGACY Pydantic models
    ├── services/
    │   ├── rag_service.py          # Ingest + retrieve + generate
    │   └── notifications.py        # Mandrill email + Twilio SMS
    └── utils/
        └── security.py             # PCI PAN mask + CVV block
```

---

# Part C — AI / LLM / embedding models

## C.1 Models actually used in code

| Model / component | Config key | Default | Where used | Why |
|---|---|---|---|---|
| **Chat LLM (OpenAI)** | `LLM_PROVIDER=openai` + `OPENAI_MODEL` | `gpt-4o-mini` | Router, RAG answers, conversation summary, escalation summary, tool ReAct | Cheap, strong tool-calling + structured output; default for MVP |
| **Chat LLM (Groq)** | `LLM_PROVIDER=groq` + `GROQ_MODEL` | `llama-3.3-70b-versatile` | Same call sites via `create_chat_model()` | Optional faster/cheaper alternative; switch without code change |
| **Embeddings** | `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | `RAGService` → Chroma ingest + similarity | OpenAI embeddings; good quality/cost for KB chunks |
| **Reranker** | (hardcoded) | FlashRank `ms-marco-TinyBERT-L-2-v2` | After MMR retrieval in `rag_service._rerank_documents` | See **§C.5** — local precision layer; replaced `rank-T5-flan` (ADR-032) |

**Factory:** `src/llm.py` → `create_chat_model(temperature=0)`  
Temperature is always `0` for deterministic support behavior.

```10:18:src/llm.py
def create_chat_model(*, temperature: float = 0) -> BaseChatModel:
    """Create the configured provider's chat model."""
    if LLM_PROVIDER == "openai":
        return ChatOpenAI(model=OPENAI_MODEL, temperature=temperature)
    if LLM_PROVIDER == "groq":
        return ChatGroq(model=GROQ_MODEL, temperature=temperature)
    raise ValueError(
        f"Unsupported LLM_PROVIDER {LLM_PROVIDER!r}; expected 'openai' or 'groq'."
    )
```

## C.2 Where each chat model call happens

| Call site | File | Role |
|---|---|---|
| Structured intent classification | `router.py` → `_get_structured_llm()` | `with_structured_output(IntentClassification)` |
| RAG answer generation | `rag_service.py` → `create_stuff_documents_chain` | Grounded answer from retrieved docs |
| Conversation summary | `nodes.py` → `summarize_conversation_node` | Operator-friendly recap |
| Escalation technical summary | `graph.py` → `_generate_escalation_summary` | Ticket handoff text |
| Tool ReAct agent | `graph.py` → `_get_tool_llm()` | `bind_tools(SETOMATIC_TOOLS)` then loop |

## C.3 Doc drift warning

Older docs (`README.md`, `TECH_STACK.md`, parts of `ENVIRONMENT.md`) sometimes still say HuggingFace `all-MiniLM-L6-v2` or per-node `ROUTER_OPENAI_MODEL`. **Live code uses OpenAI embeddings + single `OPENAI_MODEL` / `GROQ_MODEL` via `create_chat_model()`.** Trust `src/config.py` + this guide.

## C.4 API keys

| Secret | Declared in config.py? | Who reads it |
|---|---|---|
| `OPENAI_API_KEY` | No | LangChain/OpenAI SDK from process env after `load_dotenv()` |
| `GROQ_API_KEY` | No | LangChain Groq when provider is groq |
| Twilio / SMTP | Yes | `notifications.py` |

## C.5 Why FlashRank is used (important)

**Short answer:** Vector search (MMR in Chroma) alone is not precise enough for operator KB answers. FlashRank is a **second-pass local reranker** that re-orders the MMR candidates by true query relevance before the LLM sees them.

### Problem it solves

1. **MMR is recall-oriented.** It pulls a wide candidate set (`k=12`, `fetch_k=40`) so the right article is usually *somewhere* in the pool — but the top hits are often not the best ones (similar wording, wrong category).
2. **Wrong top docs → wrong LLM answer.** If cashbox / receipt-printer / portal FAQ chunks are ranked below weaker “connection error” chunks, the model refuses or gives irrelevant steps.
3. **Paid cross-encoder / LLM-as-reranker costs money and latency** on every turn. FlashRank runs **locally (ONNX)** with no extra OpenAI call.

### Why this specific model

| Choice | Reason |
|---|---|
| FlashRank library | Lightweight local reranking; model files cached under `flashrank_cache/` |
| Model `ms-marco-TinyBERT-L-2-v2` | Small, fast TinyBERT cross-encoder trained on MS MARCO passage ranking |
| Replaced earlier `rank-T5-flan` | ADR-032: `rank-T5-flan` **demoted correct operator chunks** (kiosk cashbox, receipt printer) and caused RAG refusals even when MMR had good hits |
| Wider window: MMR 12 → rerank top **6** (was top 4) | Narrow top-4 dropped usable companions; top-6 keeps better FAQ precision |

### Where it runs in code

```
User query
  → Chroma MMR retrieve (up to 12 docs)
  → FlashRank `_rerank_documents(..., top_k=6)`   ← here
  → co-retrieval of companion articles
  → LLM generate answer
```

| Function | File | Role |
|---|---|---|
| `_get_reranker()` | `rag_service.py` | Lazy-load `Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir=flashrank_cache)` |
| `_rerank_documents(query, documents, top_k=6)` | `rag_service.py` | Build passages → `ranker.rerank` → return top docs in new order |
| Called from | `_invoke_rag` | Every RAG query |

### Why not skip it?

Without FlashRank:

- Broad intents like `technical_support` (no category filter — ADR-033) send a **large noisy pool** to the LLM.
- Operator FAQ precision drops; wrong articles win; answers look “hallucinated” or refuse.

With FlashRank:

- Cheap local precision layer after cheap embedding recall.
- Lets the system keep a **wide MMR net** without stuffing 12 mediocre chunks into the prompt.

### Ops notes

- Model files live in `flashrank_cache/ms-marco-TinyBERT-L-2-v2/`.
- After changing the FlashRank model name: restart the process; re-test RAG rows (printer, cashbox, portal login).
- Formal decisions: **ADR-030**, **ADR-032** in [DECISIONS.md](DECISIONS.md).

---

# Part D — Frameworks, libraries, third-party services

## D.1 Dependencies (`pyproject.toml`) and purpose

| Package | Purpose in this project |
|---|---|
| `fastapi` + `uvicorn` | Production HTTP API |
| `streamlit` | Local demo UI |
| `langgraph` | State machine orchestration + `MemorySaver` |
| `langchain` / `langchain-openai` / `langchain-groq` / `langchain-chroma` / `langchain-community` / `langchain-text-splitters` / `langchain-classic` | LLM, tools, RAG chain, loaders, Chroma |
| `pydantic` | Request schemas + tool args + structured router output |
| `python-dotenv` | Load `.env` |
| `requests` | All Setomatic HTTP tool calls + status page |
| `beautifulsoup4` | Parse status HTML |
| `cloudscraper` | (declared) Cloudflare-aware scraping if needed |
| `httpx` | Declared; tools primarily use `requests` |
| `flashrank` | Local reranker |
| `docx2txt` / `pypdf` | KB document extraction |
| `twilio` | Live SMS |
| `protobuf<=3.20.3` | Pin for LangChain compatibility |
| `torch` / `torchvision` / `sentence-transformers` | Transitive / FlashRank / ML stack support |
| `langchain-huggingface` | Available; embeddings path in code is OpenAI |

## D.2 External services

| Service | Used for | Config |
|---|---|---|
| OpenAI API | Chat + embeddings (default) | `OPENAI_API_KEY`, models |
| Groq API | Optional chat | `LLM_PROVIDER=groq`, `GROQ_API_KEY` |
| Setomatic beta API | Loyalty, txs, kiosk, POS, remote, reports | `SETOMATIC_BASE_URL` |
| setomaticsystems.com/status | Global outage scrape | No key |
| Mandrill SMTP | Escalation / resolution email | SMTP_* vars |
| Twilio | Escalation / resolution SMS | TWILIO_* + `ESCALATION_SMS_TO` |

---

# Part E — Environment variables & configuration

All app settings that belong in code are read in **`src/config.py`**.

### Helper functions

| Function | Params | Returns | Why |
|---|---|---|---|
| `_env_str(name, default)` | env name, default string | stripped string or default | Avoid empty string overriding defaults |
| `_env_bool(name, default)` | env name, default bool | bool | Parse `false/0/no` vs everything else |

### Config variables

| Variable | Default | Stores | Used by | If you change it |
|---|---|---|---|---|
| `SETOMATIC_BASE_URL` | beta Setomatic host | API base URL | All tools | Points tools at different environment |
| `LLM_PROVIDER` | `openai` | `"openai"` or `"groq"` | `llm.py` | Switches entire chat stack |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model id | When provider=openai | Cost/quality/latency tradeoff |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Chat model id | When provider=groq | Same |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model | `RAGService` | **Must re-ingest** (`delete chroma_db/`) after change |
| `USE_LIVE_NOTIFICATIONS` | `false` | Live vs mock notify | `NotificationService` | `false` = log only (safe local) |
| `TWILIO_ACCOUNT_SID` / `AUTH_TOKEN` / `FROM_NUMBER` | empty | Twilio creds | SMS | Required when live SMS |
| `ESCALATION_SMS_TO` | empty | On-call phone | SMS destination | Who gets store-down SMS |
| `SMTP_HOST` | `smtp.mandrillapp.com` | SMTP host | Email | Mail provider |
| `SMTP_PORT` | `587` | Port | Email | Usually STARTTLS |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | empty | SMTP auth | Email | Mandrill key as password typically |
| `FROM_EMAIL` | `support@spyderwash.com` | From header | Email | Sender identity |
| `ESCALATION_EMAIL` | `support@setomaticsystems.com` | To address | Escalation/resolution | Who receives tickets |
| `OPENAI_API_KEY` | (none) | Secret | OpenAI SDK | Required for default stack |
| `GROQ_API_KEY` | (none) | Secret | Groq SDK | Required if provider=groq |

`load_dotenv()` runs in `config.py`, `server.py`, and `app.py`.

---

# Part F — Database / vector store structure

There is **no SQL database** in MVP.

## F.1 Session memory (LangGraph)

- **Store:** `MemorySaver` (in-process RAM)
- **Key:** `thread_id` = API `session_id` (or Streamlit UUID)
- **Stores:** Full `AgentState` checkpoint per thread
- **Limitation:** Lost on process restart; not shared across replicas

## F.2 ChromaDB (`./chroma_db/`)

Persistent local vector store for KB chunks.

### Important metadata fields on each document

| Field | Meaning |
|---|---|
| `article_id` | e.g. `KB-NET-001` (v2.2); empty for generic/bible chunks sometimes |
| `category` | v2.2 category (Machines Not Working, Refund Request, …) |
| `product` | Product tag from METADATA line |
| `intent` | Article intent tag |
| `search_terms` | Search keywords from article |
| `status` | `current` / `deprecated` |
| `co_retrieval_ids` | `;`-joined companion article IDs |
| `source_file` | Origin filename |
| `doc_type` | `kb_article`, `overview`, `general`, bible-related, etc. |
| `brand` | e.g. SpyderWash / Speed Queen |
| `source_priority` | `primary` (v2.2) vs `secondary` |

### Retrieval pipeline

1. MMR search: `k=12`, `fetch_k=40`, `lambda_mult=0.5` (+ optional metadata filter)  
2. FlashRank rerank → top 6  
3. Co-retrieval of companion articles  
4. LLM generation with Section 0 rules in system prompt  

**Re-ingest:** delete `chroma_db/` and restart after KB or embedding model changes.

---

# Part G — Authentication & security

## G.1 Authentication (current)

**There is no API auth on the agent today** (no API key/JWT middleware on `server.py`).  
Production plan: gateway auth in front (.NET / infra) — see ROADMAP.

CORS allowlist restricts browser origins: SpyderWash domains + localhost ports.

## G.2 PCI / security handling

| Control | Function | Behavior |
|---|---|---|
| Mask PAN on ingress | `sanitize_user_text` → `mask_credit_cards` | Replaces 15/16-digit card patterns with `**-**-****-LAST4` before graph |
| Block CVV/track | `contains_prohibited_card_auth_data` in `semantic_router` | Sets intent `pci_sensitive_data` **before any LLM** |
| Static PCI refusal | `pci_guardrail_node` | Hardcoded message, no LLM |
| Mask outbound | `sanitize_outbound_text` in notifications | Escalation email/SMS scrubbed |
| No live hardware status | `hardware_lookup_attempted` → `guardrail_node` | Portal redirect |
| Out-of-domain / injection | `out_of_domain` → `handle_out_of_domain` | Static refusal, no LLM |
| OperatorId in tools | Hardcoded `4` in tools | Request `operator_id` is for escalation display only (today) |

### Security variables (why they exist)

| Variable | Why defined |
|---|---|
| `_VISA_MC_PATTERN` / `_AMEX_PATTERN` | Detect PANs to mask |
| `_PCI_AUTH_KEYWORDS` / `_CVV_VALUE_PATTERN` | Detect forbidden auth data |
| `_PCI_SENSITIVE_INTENT` | Router-only intent string for PCI path |

---

# Part H — Error handling, logging, retries, fallbacks

## H.1 Logging

| Location | Logger / style |
|---|---|
| `server.py` | `setomatic.api` — correlation ID, latency, SUCCESS/CLIENT_ERROR/SERVER_ERROR; warn >10s |
| `tools.py` | `setomatic.tools` — request URL, status, truncated body |
| `notifications.py` | module logger — mock vs live send, failures |

## H.2 Error / fallback patterns

| Layer | Pattern |
|---|---|
| API `chat()` | `try/except` → HTTP 500 with exception detail |
| Tools | Catch Connection/Timeout → “try again in five minutes”; 4xx surface API text; 5xx system error; parse errors → support message |
| Tool ReAct | Tool exceptions become ToolMessage strings (never leave dangling tool_calls); max **6** iterations |
| RAG empty filter | `query()` retries **without** metadata filter if filtered retrieval empty |
| RAG no KB | Returns error string if vectorstore missing |
| Notifications | Missing creds → log error, return False; mock mode always “succeeds” |
| Router safety nets | Domain keywords override false OOD; offline statements → `machine_down`; recharge failures → `technical_support` |
| Escalation dedup | Duplicate outage → `post_escalation_ack` instead of second ticket |
| Mid-workflow gibberish | `workflow_reminder_node` instead of wrong path |

**No automatic HTTP retries** on Setomatic calls (single attempt + timeout). Timeout pairs are typically `(10, 12)` or `(10, 15)` seconds.

---

# Part I — Complete request / response contract

## I.1 Production API

**Endpoint:** `POST /api/v1/agent/chat`  
**Health:** `GET /health`

### Request (`ChatRequest`)

| Field | Type | Required | Why |
|---|---|---|---|
| `operator_id` | int | Yes | Stored in state for escalation context |
| `session_id` | str | Yes | LangGraph `thread_id` (memory partition) |
| `message` | str | Yes | Operator text (sanitized) |
| `operator_name/email/phone` | str | No | Escalation email contact block |

### Response (`ChatResponse`)

| Field | Type | Meaning |
|---|---|---|
| `reply` | str | Last non-empty AIMessage content |
| `detected_intent` | str | `current_intent` from router (or `unknown`) |
| `requires_escalation` | bool | `escalation_dispatched` this turn |

### Internal graph invoke payload

```python
{
  "messages": [("user", safe_message)],
  "operator_id": ...,
  # optional operator_name/email/phone
}
config = {"configurable": {"thread_id": session_id}}
```

---

# Part J — AgentState (all state variables)

Defined in `src/agent/state.py`.

| Field | Type / reducer | Why defined | Impact if wrong |
|---|---|---|---|
| `messages` | Sequence + `add_messages` | Conversation history | Breaks multi-turn / tool message validity |
| `context` | Optional[str] | Legacy context slot | Rarely used today |
| `current_intent` | Optional[str] | Router classification | Wrong node routing |
| `hardware_lookup_attempted` | Optional[bool] | Live status ask → guardrail | Can block valid help if true wrongly |
| `escalation_required` | Optional[bool] | Enter outage/escalation paths | False negatives delay tickets |
| `api_action_required` | Optional[bool] | Route to `tool_node` | Refund/tech support must stay false |
| `blast_radius` | Optional[str] | `single_machine` / `entire_location` | Controls escalate vs troubleshoot |
| `troubleshooting_failed` | Optional[bool] | Top-level escalate signal | Decoupled from entity merge quirks |
| `escalation_dispatched` | Optional[bool] | Ticket already sent | Dedup / post-escalation routing |
| `dispatched_tickets` | Optional[list] | Open TKT IDs | Resolve removes; summary uses |
| `all_session_tickets` | Optional[list] | Append-only ticket history | Summary must list all |
| `ticket_email_ids` | Optional[dict] | TKT → Message-ID | Threaded resolution replies |
| `operator_id/name/email/phone` | Optional | Contact for tickets | Email content quality |
| `last_ticket_summary` | Optional[str] | Dedup similarity | Duplicate tickets if empty |
| `last_ticket_blast_radius` | Optional[str] | Blast-aware dedup | Wrong duplicate detection |
| `ticket_notes` | Optional[list] | Post-ticket operator notes | Lost context for support |
| `callback_number` | Optional[str] | Callback phone after ticket | Missed callback |
| `extracted_entities` | dict + `merge_dicts` | Card numbers, flags, dates, device ids… | Overwrite would break multi-step tools |

### `merge_dicts(old, new) -> dict`

**Purpose:** LangGraph reducer so partial entity updates merge.  
**Why:** Without it, turn-2 `{confirmation: True}` would wipe turn-1 `card_number`.  
**Called by:** LangGraph when nodes return `extracted_entities`.

---

# Part K — Module-by-module: classes, functions, variables

## K.1 `src/llm.py`

| Symbol | Kind | Purpose |
|---|---|---|
| `create_chat_model(*, temperature=0)` | function | Build ChatOpenAI or ChatGroq |

**Params:** `temperature` (float, default 0)  
**Returns:** `BaseChatModel`  
**Called from:** router, nodes, graph, rag_service  
**Impact:** Controls all generative intelligence in the app

---

## K.2 `src/config.py`

See Part E. Module runs `load_dotenv()` on import.

---

## K.3 `src/utils/security.py`

| Symbol | Purpose | Inputs | Returns | Called from |
|---|---|---|---|---|
| `mask_credit_cards` | Mask PAN patterns | `text: str` | masked str | sanitize_* |
| `contains_prohibited_card_auth_data` | Detect CVV/track | `text: str` | bool | `semantic_router` |
| `sanitize_user_text` | Ingress scrub | `text: str` | masked str | `server.py`, `app.py`, `routes.py` |
| `sanitize_outbound_text` | Egress scrub | `text: str` | masked str | `notifications.py` |

---

## K.4 `src/api/server.py`

| Symbol | Purpose | Key details |
|---|---|---|
| `ChatRequest` | Request model | operator_id, session_id, message, optional contacts |
| `ChatResponse` | Response model | reply, detected_intent, requires_escalation |
| `app` | FastAPI app | CORS + middleware |
| `_MONITORED_PATHS` | Why: only chat gets full telemetry | `{"/api/v1/agent/chat"}` |
| `telemetry_middleware` | Latency + correlation logs | Async middleware |
| `_extract_reply` | Find last non-empty AIMessage | Avoids empty tool-call placeholders |
| `chat` | Main handler | sanitize → invoke → response |
| `health` | Liveness | `{status, service}` |

**`chat` workflow:**

1. `config.thread_id = session_id`  
2. `safe_message = sanitize_user_text(message)`  
3. Build initial state with operator fields  
4. `compiled_graph.invoke(...)`  
5. Extract reply/intent/`escalation_dispatched`  

**Impact:** Only production boundary for .NET/React.

---

## K.5 `src/api/schemas.py` + `routes.py` (legacy)

| Symbol | Purpose | Status |
|---|---|---|
| `QueryRequest/Response`, `NotificationRequest` | Old models | Do not extend |
| `query_agent` | `/query` without proper session threading | Deprecated |
| `notify_sms` / `notify_email` | Bypass graph notifications | Deprecated |

---

## K.6 `src/agent/router.py`

### Important constants (why defined)

| Constant | Why |
|---|---|
| `_PCI_SENSITIVE_INTENT` | Dedicated PCI route label |
| `_GREETING_PHRASES` | Pre-LLM greeting short-circuit (save cost/latency) |
| `_SUMMARY_PHRASES` | Pre-LLM summary short-circuit |
| `_PRODUCT_OVERVIEW_PHRASES` | Force RAG for “what is SpyderWash” |
| `_SHOW_MORE_PHRASES` + `_PAGINATION_REGEX` | Keep API intent for pagination |
| `_OUTAGE_WORKFLOW_INTENTS` | Intents that enter blast/troubleshoot flow |
| `_WORKFLOW_PROMPT_MARKERS` | Detect active outage assistant prompts |
| `_RESOLUTION_PHRASES` | Positive resolution language |
| `_TYPO_MAP` / `_NEGATION_WORDS` | Heuristic robustness |
| `_ENTIRE_MARKERS` / `_ENTIRE_SHORT` / `_NUMBER_WORDS` / `_NUMERIC_COUNT_RE` | Infer blast radius |
| `SYSTEM_PROMPT` | Full classifier instructions for LLM |
| `_DOMAIN_KEYWORDS` | Override false out_of_domain |

### Functions

| Function | Purpose | Inputs | Returns | Called from |
|---|---|---|---|---|
| `_is_greeting` | Detect greeting | text | bool | `semantic_router` |
| `_is_summary_request` | Detect summary ask | text | bool | `semantic_router` |
| `_is_product_overview_query` | Product overview | text | bool | router + `nodes._extract_metadata_filter` |
| `_is_show_more_request` | Pagination follow-up | text, messages | bool | `semantic_router` |
| `_normalize_typos` | Typo normalize | text | str | heuristics |
| `_is_resolution_message` | Resolved language | text | bool | router helpers / graph imports |
| `_assistant_in_active_outage_workflow` | Prior AI mid-workflow | prior msg | bool | fresh-outage logic |
| `_is_fresh_outage_turn` | New outage same session | intent, prior, entities | bool | `semantic_router` |
| `_prior_is_blast_radius_question` | Prior asked scope | prior | bool | `semantic_router` |
| `infer_blast_radius` | Heuristic scope | user_msg | `single_machine` / `entire_location` / None | router + graph routing |
| `_contains_domain_keyword` | Domain term present | text | bool | OOD override |
| `_get_structured_llm` | Lazy structured LLM | — | LLM | `semantic_router` |
| `semantic_router` | **Entry node** | `AgentState` | partial state update | graph node `router` |

### Class `IntentClassification`

| Field | Meaning |
|---|---|
| `intent` | One of allowed intent strings |
| `hardware_lookup_attempted` | Live status ask |
| `escalation_required` | Emergency/human escalate flag |
| `api_action_required` | Must call tools |
| `extracted_entities` | card_number, dates, blast_radius, device_id, command, etc. |

### `semantic_router` internal workflow

1. Empty messages → `{}`  
2. PCI check → early return  
3. Greeting / summary / product overview / show-more short-circuits  
4. Build prior+current prompt → structured LLM  
5. Safety nets (domain, recharge failure, offline report)  
6. Fresh-outage flag resets; blast inference  
7. Return intent + flags + entities (+ promote blast/troubleshooting_failed)

**Impact:** Wrong classification = wrong entire product behavior.

---

## K.7 `src/agent/nodes.py`

### Important variables

| Variable | Why |
|---|---|
| `_rag_service` / `get_rag_service()` | Singleton RAG (expensive to rebuild) |
| `_BRAND_FILTER_MAP` | Map query brand words → Chroma brand filter |
| `_INTENT_TO_CATEGORY_MAP` | Intent → v2.2 category filter |
| `_TROUBLESHOOT_MARKERS` | Detect troubleshooting answers for resolve prompt |
| `_TROUBLESHOOT_INTENTS` | Intents that may append “Did this resolve?” |
| `_FOLLOWUP_*` / `_KB_ARTICLE_PATTERN` | Short follow-up expansion (ADR-036) |
| `_SUMMARY_SYSTEM_PROMPT` / `_SUMMARY_SKIP_PHRASES` | Summary node behavior |

### Functions

| Function | Purpose | Params | Returns | Called from | Impact |
|---|---|---|---|---|---|
| `get_rag_service` | Lazy RAG singleton | — | `RAGService` | RAG nodes | One vectorstore per process |
| `_extract_metadata_filter` | Build Chroma filter | state | dict/None | `retrieve_and_generate` | Narrows retrieval |
| `_answer_contains_troubleshooting` | Marker count ≥2 | answer | bool | RAG node | Controls resolve prompt |
| `_get_prior_ai_content` | Prior AI text | messages | str/None | follow-up expand | Context for short “yes” |
| `_is_short_followup` | Affirmative short msg | text | bool | expand | Avoid bad retrieval |
| `_expand_followup_query` | Expand query + optional article filter | messages | `(query, filter)` | RAG node | ADR-036 quality |
| `retrieve_and_generate` | RAG_Node | state | messages (+ entities) | graph `rag_agent` | Main KB answers |
| `guardrail_node` | Refuse live hardware | state | AIMessage | graph | Compliance |
| `pci_guardrail_node` | Refuse CVV | state | AIMessage | graph | PCI |
| `handle_greeting` | Hi/thanks/bye + flag reset | state | messages + cleared flags | graph | Session soft reset |
| `workflow_reminder_node` | Re-ask Yes/No | state | AIMessage | graph | Prevents false escalate |
| `handle_out_of_domain` | Static OOD refuse | state | AIMessage | graph | Injection safety |
| `summarize_conversation_node` | LLM recap + tickets | state | AIMessage | graph | Operator recap |

### `retrieve_and_generate` workflow

1. Expand follow-up query if needed  
2. Build metadata filter  
3. `rag_service.query(...)`  
4. If troubleshooting markers (rules) and no trailing offer question → append “Did this resolve?” and set `troubleshooting_done=True`

---

## K.8 `src/agent/graph.py` (orchestration core)

### Important constants

| Constant | Why |
|---|---|
| `_ESCALATION_WORKFLOW_INTENTS` | Intents entering outage multi-turn flow |
| `_BLAST_RADIUS_REPLY_PHRASES` | Detect scope replies |
| `_ESCALATION_SUMMARY_PROMPT` | Technician handoff format |
| `_HOWTO_*` / `_CONTINUATION_MARKERS` | Post-escalation: RAG vs ticket note |
| `_PHONE_RE` | Extract callback numbers |
| `_STATUS_KEYWORDS` / `_POST_ESC_HUMAN_PHRASES` | Post-ticket routing |
| `_TOOL_SYSTEM_PROMPT` | ReAct tool agent instructions |
| `MAX_ITERATIONS = 6` | Cap tool loops |
| `SETOMATIC_TOOLS` import | Bound tool list |

### Helper functions

| Function | Purpose | Returns / effect |
|---|---|---|
| `_is_conversational_workflow_reply` | Short workflow chatter vs real issue | bool |
| `_extract_escalation_context` | Pull context for summary | str |
| `_generate_escalation_summary` | LLM ISSUE/LOCATION/… block | str |
| `_postprocess_summary` | Normalize summary | str |
| `_get_prior_assistant_content` | Prior AI | str/None |
| `_user_indicates_resolved` | Resolution phrasing | bool |
| `_is_duplicate_outage` | Jaccard + blast dedup | bool |
| `_is_howto_or_info_query` | How-to detection | bool |
| `_is_continuation_of_ticket` | “also…” notes | bool |
| `_format_conversation_for_email` | Transcript | str |
| `_resolve_operator_contact` | name,email,phone tuple | tuple |

### Nodes (purpose → impact)

| Function | Purpose | Key return state | Called as graph node |
|---|---|---|---|
| `escalation_node` | Create `TKT-…`, email+SMS | `escalation_dispatched=True`, ticket lists | `escalation_node` |
| `new_issue_after_escalation_node` | Reset workflow for new issue | entities reset, keep tickets | `new_issue_after_escalation` |
| `_route_after_new_issue` | Chain next outage step | edge target string | conditional edge |
| `blast_radius_check_node` | Ask one vs store | `blast_radius_asked` | `blast_radius_check` |
| `clarify_issue_node` | Ask symptoms | `clarify_asked` | `clarify_issue` |
| `troubleshoot_first_node` | Outage RAG + resolve Q | `troubleshooting_done` | `troubleshoot_first` |
| `escalation_resolved_node` | Close tickets + resolve mail | remove open tickets | `escalation_resolved` |
| `troubleshoot_success_node` | Ack fix | optional ticket reminder | `troubleshoot_success` |
| `confirm_escalation_node` | Ask permission (single machine) | `escalation_confirmation_asked` | `confirm_escalation` |
| `escalation_declined_node` | Decline path contact info | clears confirm flag | `escalation_declined` |
| `exit_escalation_gate_node` | Leave confirm gate → RAG | clears gate | `exit_escalation_gate` |
| `human_escalation_clarify_node` | Ask issue before human escalate | `human_escalation_asked` | `human_escalation_clarify` |
| `post_escalation_ack_node` | Post-ticket ack/notes/callback | notes / callback | `post_escalation_ack` |
| `_reset_tool_llm` / `_get_tool_llm` | Bind tools to LLM | singleton | `tool_node` |
| `tool_node` | ReAct tool loop | new messages; clears outage flags | `tool_node` |
| `route_after_classifier` | Priority router | next node name | conditional after router |
| `route_after_rag` | After RAG escalate? | `__end__` / escalate / confirm | conditional after rag |
| `create_agent_graph` | Wire StateGraph + MemorySaver | compiled app | module load → `agent_app` |

### `tool_node` workflow

1. Bind tools via `_get_tool_llm()`  
2. Inject TODAY date + entity hints so LLM doesn’t re-ask  
3. Loop ≤6: invoke LLM → if tool_calls, execute each and append ToolMessage → else break  
4. Clear troubleshooting workflow flags (tools = context switch)

### `create_agent_graph` edges

- Entry: `router`  
- Conditional map from `route_after_classifier` to all action nodes  
- `rag_agent` → `route_after_rag` → END / escalation / confirm  
- Most nodes → `END`  
- `new_issue_after_escalation` → `_route_after_new_issue` chain  

**Exported:** `agent_app = create_agent_graph()`

---

## K.9 `src/agent/tools.py`

### Module variables (why)

| Variable | Why |
|---|---|
| `_BROWSER_HEADERS` | Status page scrape looks like a browser |
| `_CARD_NUMBER_PATTERN` | Validate card args before API |
| `_*_URL` / `_*_OPERATOR_ID` | Endpoint paths; OperatorId hardcoded to `4` (MVP) |
| `_TRANSACTION_PAGE_SIZE = 5` | Avoid LLM context overflow |
| `_REPORT_ENDPOINTS` / `_REPORT_FORMATTERS` / `_REPORT_TITLES` | Unified report tool dispatch |
| `_REPORT_HEADERS` | JSON Accept headers |
| `SETOMATIC_TOOLS` | List bound to ReAct LLM |

### Schemas (input contracts)

| Schema | Key fields | Validates |
|---|---|---|
| `LoyaltyBalanceSchema` | `card_number` 4–15 | Pattern |
| `TransactionHistorySchema` | card, count 1–20, include_refunds, dates, page_no | Dates ISO |
| `KioskPurchasesSchema` / `KioskRechargesSchema` | dates, location, imei, page_* | Dates required |
| `POSTransactionsSchema` | dates, card_code, order_type, account_type, filters, page_* | Enums via ints |
| `RemoteDeviceCommandSchema` | device_id, command Dispense/Reboot, amount | Command normalize |
| `ReportSchema` | report_type, locations, from/to dates, extras | Report type set |

### Helper functions

| Function | Purpose |
|---|---|
| `_normalize_card_number` | Strip `LC-` prefixes |
| `_convert_date_to_api_format` | ISO → API date |
| `_format_revenue_by_location/position/machine_type/month` | Format report rows |
| `_format_attendant_detail` / `_format_promotional_fund` / `_format_pos_transactions_report` | Formatters |

### Tools (each returns `str` for LLM)

| Tool | HTTP | Params (summary) | Error handling | Called by |
|---|---|---|---|---|
| `get_loyalty_balance` | GET CheckLoyaltyCardBalance | card_number | 4xx/5xx/timeout/parse | ReAct |
| `get_transaction_history` | GET ViewAllTransactionSearch (+ balance precheck) | card, count, refunds, dates, page | same | ReAct |
| `check_global_system_status` | scrape status site | none | scrape failure message | ReAct |
| `get_kiosk_purchases` | kiosk purchases API | dates, filters, page | same | ReAct |
| `get_kiosk_recharges` | kiosk recharges API | dates, filters, page | same | ReAct |
| `get_pos_transactions` | POS txs API | dates, filters, page | same | ReAct |
| `send_remote_device_command` | POST SendCommondToRemoteDevice | device_id, command, amount | validate amount; same HTTP | ReAct |
| `get_report` | one of 7 report endpoints | report_type, locations, dates… | same | ReAct |

**Shared tool workflow:** validate → HTTP with timeout → map status → format operator text → catch network/parse.

**Impact:** Wrong tool args or OperatorId=4 assumption → wrong live data for operators.

---

## K.10 `src/services/rag_service.py`

### Regex / marker constants

| Constant | Why |
|---|---|
| `_ARTICLE_PATTERN` | Split v2.2 ARTICLE START/END |
| `_METADATA_PATTERN` | Parse METADATA line |
| `_CO_RETRIEVAL_PATTERN` | Companion article rules |
| `_ARTICLE_ID_REF_PATTERN` | Find `KB-…` IDs |
| `_V22_FILENAME_MARKERS` / `_BIBLE_FILENAME_MARKERS` | Detect file types |
| Bible start/end markers | Selective ingest windows |

### Functions / methods

| Symbol | Purpose | Returns |
|---|---|---|
| `_is_v22_file` / `_is_bible_file` | Filename checks | bool |
| `_parse_v22_articles` | Articles + Section0 + visuals | tuple |
| `_parse_bible_selective` | Troubleshoot + operator FAQ chunks | list[Document] |
| `_get_reranker` | Lazy FlashRank | Ranker |
| `_rerank_documents` | Rerank to top_k | list[Document] |
| `RAGService.__init__` | Load or ingest Chroma | — |
| `_load_section0_prompt` | Cache Section 0 | — |
| `_find_v22_file` | Path to v2.2 | str/None |
| `load_and_process_documents` | Full KB walk | chunks/None |
| `_ingest_v22` / `_ingest_bible` / `_ingest_generic` | Per-source ingest | list |
| `initialize_vectorstore` | Persist Chroma | Chroma |
| `_build_retriever` | MMR + filter | retriever |
| `_fetch_co_retrieval_docs` | Companion fetch | list |
| `_build_system_prompt` / `_condense_section0` | Generation rules | str |
| `query` | Public RAG entry (+ filter fallback) | `{answer, context}` |
| `_invoke_rag` | retrieve→rerank→co→generate | dict |

**Called from:** `nodes.get_rag_service()` / `retrieve_and_generate` / `troubleshoot_first_node` (via same service).

---

## K.11 `src/services/notifications.py`

| Symbol | Purpose | Inputs | Returns | Impact |
|---|---|---|---|---|
| `EscalationResult` | Result dataclass | email_sent, sms_sent, message_id | — | Graph stores message_id for threading |
| `send_sms` | Twilio or mock | to, message | bool | On-call alert |
| `send_email_html` | SMTP HTML + threading headers | to, subject, html, ids | bool | Ticket email |
| `send_email` | Plain wrapper | to, subject, body | bool | Legacy routes |
| `_parse_location_from_summary` | LOCATION line | summary | str/None | SMS/email location |
| `_build_escalation_html` | HTML template | ticket + contact + summary | html | Branding |
| `send_escalation` | Full dispatch | ticket fields | EscalationResult | Creates support ticket path |
| `send_resolution` | Threaded resolve notify | ticket_id, summary, message_id | bool | Closes loop with support |

**Gate:** `USE_LIVE_NOTIFICATIONS`.

---

## K.12 `app.py` (Streamlit)

| Symbol | Purpose |
|---|---|
| `_now_ts` / `_render_ts` | Bubble timestamps |
| `_NODE_LABELS` / `_node_label` | Live status text while streaming nodes |
| `_extract_final_response` | Same last-AI walk as API |
| `_render_routing_diagnostics` | Sidebar debug (intent/flags/path) |
| Session keys | `messages`, `thread_id`, `processing`, diagnostics |

**Main loop:** sanitize prompt → `compiled_graph.stream` → show reply + diagnostics.

---

## K.13 `main.py` (legacy)

| Function | Purpose |
|---|---|
| `stream_turn` | Console stream one turn |
| `run_multi_turn_test` | Scripted multi-turn |

Prefer `server.py` / `app.py`.

---

# Part L — Intent → node routing (summary)

| Intent / condition | Typical node |
|---|---|
| greeting | `greeting_node` |
| conversation_summary | `summarize_node` |
| out_of_domain | `out_of_domain_node` |
| pci_sensitive_data | `pci_guardrail_node` |
| hardware_lookup_attempted | `guardrail_node` |
| loyalty / tx / kiosk / POS / remote / report / system_status (`api_action_required`) | `tool_node` |
| refund_request / technical_support / general_query | `rag_agent` |
| machine_down / machines_not_starting / … | blast → clarify → troubleshoot → confirm/escalate |
| emergency_store_down / entire_location | escalate (critical) |
| critical_outage | escalate immediately |
| escalation_request (first) | `human_escalation_clarify` |
| post ticket | `post_escalation_ack` / resolve / new issue |

Full priority order lives in `route_after_classifier` (see [CODE_FLOW_AND_FUNCTIONS.md](CODE_FLOW_AND_FUNCTIONS.md) §6.9).

---

# Part M — Setup, run, test, deploy

## M.1 Setup

```bash
uv sync
# Create .env at repo root with at least:
# OPENAI_API_KEY=sk-...
# Optional: LLM_PROVIDER, models, SETOMATIC_BASE_URL, notification vars
```

## M.2 Run

```bash
# Production API
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# Streamlit demo
uv run streamlit run app.py
```

## M.3 Test

```bash
uv run python -m unittest tests.test_outage_workflow tests.test_security -v
```

Manual TC1/TC2: [TESTING.md](TESTING.md), [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md)

## M.4 Deploy (current reality)

- This repo does **not** contain full production infra-as-code.  
- Target: containers alongside SpyderWash (Rackspace preferred) — [ROADMAP.md](ROADMAP.md), [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md)  
- Inject secrets via env; never commit `.env`  
- Put auth in front of `:8000`  
- Replace `MemorySaver` before multi-replica scale  
- Consider shared vector DB (Qdrant) instead of local `chroma_db/`

---

# Part N — Known limitations & troubleshooting

## N.1 Known limitations

| Limitation | Detail |
|---|---|
| No API authentication | Agent endpoint is open unless gateway protects it |
| MemorySaver not durable | Restart loses sessions; not multi-instance safe |
| OperatorId=4 hardcoded in tools | Request `operator_id` not yet wired into Setomatic tool calls |
| No agent refund execute | By design (ADR-028) — portal guidance only |
| No live machine telemetry | Guardrail refuses; portal only |
| Local Chroma | Per-machine index; re-ingest after KB changes |
| Doc drift | Some older markdown still mention MiniLM / per-node OpenAI model envs |

## N.2 Troubleshooting

| Symptom | Check |
|---|---|
| RAG answers empty / wrong | Delete `chroma_db/`, ensure KB DOCX present, `OPENAI_API_KEY` set, restart |
| Tools fail | `SETOMATIC_BASE_URL`, network, OperatorId=4 assumption, tool logs |
| Escalation “works” but no email/SMS | `USE_LIVE_NOTIFICATIONS=true` + Twilio/SMTP vars |
| Wrong routing | Streamlit diagnostics sidebar; inspect `current_intent` / entities |
| PCI refusal unexpected | Message contained CVV/track keywords |
| Session amnesia | New `session_id` or server restart cleared MemorySaver |
| Slow chat (>10s) | server logs WARN; LLM/API latency |
| Import / protobuf errors | Keep `protobuf<=3.20.3`; `uv sync` |

---

# Part O — Suggested reading order for a new developer

1. This guide (Parts A–C, I–J)  
2. `src/agent/state.py`  
3. `src/api/server.py`  
4. `src/agent/router.py` (`semantic_router`)  
5. `src/agent/graph.py` (`route_after_classifier`, `create_agent_graph`)  
6. `src/agent/nodes.py` (`retrieve_and_generate`)  
7. One tool end-to-end in `tools.py` (`get_loyalty_balance`)  
8. `src/services/rag_service.py` (`query`)  
9. `src/services/notifications.py` (`send_escalation`)  
10. Run Streamlit and watch routing diagnostics  

---

# Part P — Related docs index

| Doc | Use |
|---|---|
| [CODE_FLOW_AND_FUNCTIONS.md](CODE_FLOW_AND_FUNCTIONS.md) | Shorter flow + function map |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Runtime diagrams |
| [API.md](API.md) | Integrator HTTP contract |
| [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) | Backend API scope |
| [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) | TC1/TC2 scenarios |
| [INTENT_MATRIX.md](INTENT_MATRIX.md) | Brandon matrix mapping |
| [DECISIONS.md](DECISIONS.md) | ADRs |
| [ENVIRONMENT.md](ENVIRONMENT.md) | Env reference (verify vs `config.py`) |
| [RUNBOOK.md](RUNBOOK.md) | Ops |
| [TESTING.md](TESTING.md) | Test procedures |

---

*End of Complete Developer Guide. When code changes, update this file in the same PR.*
