# Architecture Decision Records

Lightweight ADRs for decisions already made. Prevents re-debating settled choices when developing without AI assistance.

Format: **Status** | **Context** | **Decision** | **Consequences**

---

## ADR-001: Operator Agent only

**Status:** Accepted  
**Context:** Client proposals describe dual Customer + Operator agents. Current sprint scope is operator portal support only.  
**Decision:** Build and document **Operator Agent only**. Customer Agent is a separate future product.  
**Consequences:** No customer loyalty/refund flows in this repo's PRD. Shared infrastructure (RAG, hosting) may be reused later.

---

## ADR-002: Canonical API is server.py /api/v1/agent/chat

**Status:** Accepted  
**Context:** Multiple entry points existed: Streamlit in-process, `main.py` `/query`, `server.py` chat.  
**Decision:** Production integrators use `POST /api/v1/agent/chat` on [server.py](../src/api/server.py) only.  
**Consequences:** React and .NET widgets target `:8000`. Legacy `/query` deprecated. See [API.md](API.md).

---

## ADR-003: Chroma for MVP; Qdrant before multi-replica prod

**Status:** Accepted  
**Context:** KB starts small (legacy guides); Bible target ~500 pages. Chroma persists locally in `./chroma_db`.  
**Decision:** Keep **ChromaDB** through QA/UAT. Migrate to **Qdrant** (or equivalent) before running multiple API replicas.  
**Consequences:** Single-process API is fine for demo. Phase 3 roadmap includes vector DB migration. See [TECH_STACK.md](TECH_STACK.md).

---

## ADR-004: Web chat uses REST; voice uses separate WebSocket pipeline

**Status:** Accepted  
**Context:** Twilio voice requires real-time audio. Web portal chat is turn-based.  
**Decision:** Web chat = **HTTP POST per message** with `session_id`. Twilio Media Streams = **separate WebSocket service** (Phase 4).  
**Consequences:** Do not merge audio WebSocket into `/chat`. Multi-turn memory works via REST + MemorySaver.

---

## ADR-005: Troubleshoot-first escalation (Gregg)

**Status:** Accepted  
**Context:** Client rejected immediate on-call dispatch for outages.  
**Decision:** Outage intents follow: **blast-radius → KB troubleshoot → confirm → escalate on failure**. Exception: `critical_outage` skips to immediate escalation.  
**Consequences:** Complex graph routing in [graph.py](../src/agent/graph.py). Regression tests in [tests/test_outage_workflow.py](../tests/test_outage_workflow.py). See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-006: Streamlit dev-only; React QA + .NET prod

**Status:** Accepted  
**Context:** Streamlit cannot be deployed as the operator portal widget. dev2 builds React for **QA/UAT only**; Setomatic frontend team builds .NET Super Admin widget for **production**.  
**Decision:** **Streamlit** = local developer demo (in-process graph). **React** = QA/UAT HTTP client. **.NET** = production HTTP client. Both HTTP clients use the same `:8000` API.  
**Consequences:** Streamlit may show "Unknown Operator" in escalations (no contact fields). See [ROADMAP.md](ROADMAP.md) UI channels table.

---



## ADR-007: No live hardware status in chat

**Status:** Accepted  
**Context:** Agent must not hallucinate machine/port telemetry.  
**Decision:** `hardware_status` intent routes to **guardrail_node** — static refusal directing to operator portal.  
**Consequences:** No API integration for live machine state. Documented in [PRD.md](PRD.md).

---

## ADR-008: Escalation sends email + SMS today

**Status:** Accepted (interim)  
**Context:** Brandon's Intent Matrix specifies per-intent Email / SMS / both / none.  
**Decision:** **Interim:** all escalations send **both** Mandrill email and Twilio SMS. **Target (Brandon matrix):** per-intent routing in Phase 2 — notably **SMS Alert only** for Entire Store Down / `critical_outage`, Email-only for receipt printer and conditional rows.  
**Consequences:** May over-notify for intents that should be email-only. Track in [INTENT_MATRIX.md](INTENT_MATRIX.md).

---

## ADR-009: OpenAI for router, tools, and RAG

**Status:** Accepted  
**Context:** Early README mentioned Groq for RAG. Current code uses `ChatOpenAI` with `RAG_OPENAI_MODEL`.  
**Decision:** **OpenAI** (`gpt-4o-mini` default) for router, tool-calling, and RAG generation. Embeddings remain local HuggingFace.  
**Consequences:** `OPENAI_API_KEY` required. `GROQ_API_KEY` not used by current code.

---

## ADR-010: Mock server on :8001 for refund development (removed)

**Status:** Superseded / removed — see ADR-028  
**Context:** Early dev used a local mock refund API on port 8001.  
**Decision (historical):** [mock_server.py](../src/api/mock_server.py) simulated refund endpoints when `USE_MOCK_REFUNDS=true`.  
**Current:** File and env flags removed. Agent does not execute refunds — portal guidance via Bible (ADR-028).

---

## ADR-011: operator_id accepted on API but not yet in tool payloads

**Status:** Accepted (interim)  
**Context:** Frontend must pass authenticated `operator_id` per operator session. API stores it in state for escalation display.  
**Decision:** **Interim:** [tools.py](../src/agent/tools.py) hardcodes `OperatorId=4` / `LoggedInUserId=4` for Setomatic API calls. **Target:** read `state.operator_id` in Phase 1.  
**Consequences:** Wrong operator scope in prod until Phase 1. Documented in [API.md](API.md) and [ROADMAP.md](ROADMAP.md).

---

## ADR-012: KB ingestion limited to PDF and DOCX

**Status:** Accepted  
**Context:** `KB/` contains `.txt` files but [rag_service.py](../src/services/rag_service.py) only loads `.pdf` and `.docx`.  
**Decision:** Ingest PDF/DOCX only for MVP. Extend loader or convert `.txt` sources before expecting them in RAG answers.  
**Consequences:** Plain-text KB files are ignored until loader is extended.

---

## ADR-013: SpyderWash Bible as sole KB; Rackspace asset hosting

**Status:** Accepted (planning) — updated Jul 18, 2026 per Brandon email  
**Context:** Product owner is compiling “The Bible of SpyderWash” (**261 pages / 47.9 MB** per Brandon Jul 17, 2026 — previously estimated at ~500 pages). v2.2 (171 structured articles) was created specifically for AI chatbot integration and is the primary RAG source. Brandon confirmed to maintain v2.2 alongside the Bible until Bible is complete (pending: company/product overview, redesigned site/app content). Brandon’s KB Admin prototype defines structured chunks and feedback loop — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md).  
**Decision:** **Current:** dual-doc strategy — v2.2 as primary article-structured source + Bible troubleshooting **and** operator FAQ sections as supplement (ADR-030). **Target:** single Bible document when complete; retire v2.2. Rackspace Cloud Files for Bible + video assets; agent consumes via **ingest pipeline → shared vector DB**, not direct filesystem reads in production. Videos: prefer **URLs embedded in Bible sections** (Option B) over transcript RAG — ADR-029.  
**Consequences:** Article-aware ingest (ADR-030) handles current dual-doc state. Production needs Phase 3 ingest + Qdrant + Rackspace deploy. Brand wiring diagrams / PCI notes excluded from RAG; operator Installation FAQ (e.g. Relay vs Serial) is ingested. See [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).
---

## ADR-015: Structured KB chunks vs generic RAG splits

**Status:** Implemented (ADR-030)  
**Context:** Brandon’s KB Admin prototype uses **structured chunks** (chunk_id, section_id, keywords, common_queries). v2.2 provides 171 articles with ARTICLE START/ARTICLE END boundaries and explicit metadata. Previous [rag_service.py](../src/services/rag_service.py) used 500-char RecursiveCharacterTextSplitter on PDF/DOCX with filename metadata only.  
**Decision:** **Implemented (ADR-030):** v2.2 articles ingested as atomic chunks with structured metadata (article_id, category, product, intent, search_terms, status, co_retrieval_ids). Bible selectively ingested (troubleshooting + operator FAQ; wiring/PCI excluded). FlashRank `ms-marco-TinyBERT-L-2-v2` reranking + co-retrieval (ADR-032). **Target (Phase 5):** KB Admin approve workflow; Brandon’s full chunk schema with feedback loop.  
**Consequences:** Article-aware ingestion operational. Phase 5 builds admin UI + feedback loop; interim = email notification + manual re-ingest. See [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md), [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md).
---

## ADR-014: Vendor requirements doc vs Operator Agent repo scope

**Status:** Accepted  
**Context:** `SendAnywhere_546287/Requrement understading.docx` describes a full dual-agent platform (~6 months): Customer + Operator agents, API gateway, voice, live call transfer, multi-tenant PostgreSQL, admin panel, bilingual support, and low-confidence escalation. This repo delivers **Operator Agent MVP** only.  
**Decision:**  

- **In scope (this repo):** Operator web chat API, LangGraph, RAG, Setomatic tools, Gregg/Brandon escalation rules, PCI, React QA + .NET prod widget integration.  
- **Deferred to phases:** Voice (Phase 4), admin KB UI (Phase 5), Qdrant + Rackspace (Phase 3), gateway auth (Phase 2).  
- **Out of scope / different:** Customer Agent; live phone bridge to human; inbound operator SMS; vendor low-confidence escalation replaced by **intent classification + troubleshoot-first confirmation**; Rackspace preferred over vendor doc’s AWS/Azure default.  
- **Pending product decision:** Bilingual (English/Spanish), Bible image handling — documented in [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) and [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).  
**Consequences:** [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) is the traceability source. Do not mark vendor platform items as implemented in PRD/ROADMAP without code evidence.

---

## ADR-016: Escalation deduplication and state reset

**Status:** Accepted  
**Context:** Operators could repeatedly say "NO" after an escalation ticket was dispatched, generating infinite duplicate tickets with SMS/email each time. Additionally, after saying "YES" (resolved), the workflow flags persisted in state, trapping subsequent messages in the `workflow_reminder` loop instead of treating them as fresh conversations.  
**Decision:**  

- `escalation_node` sets `escalation_dispatched: true` in state after dispatch.  
- `route_after_classifier` checks this flag before routing to escalation — if already dispatched, routes to `post_escalation_ack` instead.  
- `escalation_resolved_node` performs a full state reset (clears `troubleshooting_done`, `blast_radius`, `troubleshooting_failed`, `escalation_dispatched`) so new issues can start fresh.  
**Consequences:** Max 1 escalation ticket per unresolved workflow instance. Operator must confirm resolution to start a new workflow. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-017: Entire location = immediate escalation (skip troubleshooting)

**Status:** Accepted  
**Context:** When the operator confirms the entire laundromat is offline (`blast_radius == "entire_location"`), troubleshooting steps (restart hub, check LEDs) are insufficient — the situation requires immediate human intervention. Previously, entire-location outages still went through `troubleshoot_first_node` before escalation.  
**Decision:** If blast radius is `entire_location`, skip `troubleshoot_first` and route directly to `escalation_node`. Only `single_machine` / few-machine scenarios go through KB troubleshooting before escalation.  
**Consequences:** Faster response for critical outages. Aligns `entire_location` with `critical_outage` behavior. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-018: Post-escalation fresh cycle for new issue reports

**Status:** Accepted  
**Context:** After a ticket was dispatched, operators were stuck — any message (including new issue reports like "one new machine is down") was caught by `post_escalation_ack` and could not start a fresh workflow.  
**Decision:** When the prior AI message contains escalation markers AND the user's new message is classified as an outage intent with ≥3 words (descriptive), route to `new_issue_after_escalation_node` which resets all workflow state and starts a fresh blast-radius cycle. Short/ambiguous follow-ups still route to `post_escalation_ack`.  
**Consequences:** Operators can report genuinely new issues after escalation without being stuck. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-019: technical_support intent for non-outage machine symptoms

**Status:** Accepted  
**Context:** The LLM router was classifying non-outage machine symptoms (lights, sounds, error codes, display questions) as `machine_down`, funneling them through the outage workflow (blast-radius → troubleshoot → escalate). This produced irrelevant hub/network troubleshooting for sound/light issues.  
**Decision:** Added explicit router rule distinguishing `technical_support` (symptoms: lights, sounds, errors, displays) from `machine_down` (machine physically offline/unresponsive). `technical_support` routes directly to RAG without the outage workflow. Updated system prompt rules 14-15.  
**Consequences:** Light/sound/display questions get direct KB answers. Only confirmed outages enter the escalation workflow. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-020: Card number prefix normalization

**Status:** Accepted  
**Context:** Operators type card numbers with prefixes like "LC-", "lc-", "lc " which the LLM sometimes passes through to tools. The Setomatic API only recognizes the bare number (e.g., "00000212").  
**Decision:** `_normalize_card_number()` in tools.py strips `LC-`/`lc-`/`lc ` prefixes before any API call. Applied in both `get_loyalty_balance` and `get_transaction_history`.  
**Consequences:** "balance lc-00000212" now works the same as "balance 00000212".

---

## ADR-021: On-demand conversation summary

**Status:** Accepted  
**Context:** Operators need a quick recap of issues raised, actions taken, tickets/refunds, and current status without leaving an active troubleshooting or outage workflow.  
**Decision:** Add `conversation_summary` intent with a pre-LLM phrase heuristic (`_is_summary_request`) and `summarize_conversation_node`. Route early in `route_after_classifier` so summary requests are honored even mid-workflow without clearing outage state.  
**Consequences:** Operators can say "summarise this chat" at any time. Summary uses LLM over filtered thread history; does not dispatch escalation or call Setomatic APIs.

---

## ADR-022: Transaction lookup — card validation, count, and refund filter

**Status:** Accepted  
**Context:** Invalid loyalty cards could return unrelated operator-wide transactions from the Setomatic API. Operators also need configurable result counts and separate refund vs non-refund history after `isRefund` was added to `ViewAllTransactionSearch`.  
**Decision:**  

- `get_transaction_history` pre-validates the card via `get_loyalty_balance` before fetching transactions.  
- Add `count` parameter (1–20, default 5) mapped to API `PageSize`.  
- Add `include_refunds` boolean (default `false`) mapped to API `isRefund`.  
**Consequences:** Invalid cards get a clear "not found" message. "Show my last 10 transactions" and "show refunded transactions" work via natural language tool selection. See [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md).

---

## ADR-023: Clarify vague outage reports before troubleshooting

**Status:** Accepted (updated)  
**Context:** Operators reporting only scope without symptom (e.g., "one machine") were pushed into blast-radius or troubleshooting with no actionable context. However, messages like "one machine is down" contain a clear symptom word ("down") and should NOT be treated as vague.  
**Decision:** Add `clarify_issue` node. When an outage intent is classified but the message lacks action/symptom words (down, offline, broken, error, frozen, etc.) and `clarify_asked` is not set, route to `clarify_issue`. Set `clarify_asked: true` so clarification fires at most once per cycle. The message-selection logic now prioritizes action-word presence over `_is_conversational_workflow_reply` matching — if a message contains an action word it is accepted as the issue description regardless of conversational-reply heuristics.  
**Consequences:** "one machine" alone gets a clarification question. "one machine is down" goes directly to KB troubleshooting. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-024: Streamlit routing diagnostics persistence

**Status:** Accepted  
**Context:** Sidebar intent/guardrail/escalation/API indicators in [app.py](../app.py) were written only during the processing run; `st.rerun()` after each response recreated empty placeholders, so diagnostics flashed briefly then disappeared.  
**Decision:** Persist routing diagnostics in `st.session_state.routing_diagnostics` and render from that on every Streamlit run. Update live during graph streaming and after completion.  
**Consequences:** Dev demo sidebar shows stable last-known routing state across turns. Production React/.NET clients are unaffected (they use the HTTP API, not Streamlit sidebar).

---

## ADR-025: Remove source citations from troubleshooting responses

**Status:** Accepted  
**Context:** `troubleshoot_first_node` appended a "Sources: filename [p.X] | filename [p.Y]" line to KB troubleshooting responses. PM requested removal — operators do not need to see internal document references.  
**Decision:** Remove the `context_docs` → `sources_note` block from `troubleshoot_first_node`. Troubleshooting responses now show only the KB answer followed by "Did this resolve the issue? (Yes/No)".  
**Consequences:** Cleaner operator-facing output. Source provenance is still available in ChromaDB metadata for debugging but not surfaced in responses.

---

## ADR-026: Troubleshoot success vs ticket resolution

**Status:** Accepted  
**Context:** After "Did this resolve the issue?", a "yes" was routed to `escalation_resolved_node`. When the session already had open tickets from prior escalations, that node asked "Which ticket is resolved?" instead of acknowledging that KB troubleshooting fixed the *current* issue (which had no ticket).  
**Decision:** Route positive post-troubleshooting confirmations to `troubleshoot_success_node`. That node says "Glad to hear…" first and only then reminds about remaining open tickets. `escalation_resolved_node` is reserved for resolving dispatched tickets (by ID / "all" / single open ticket).  
**Consequences:** Operators get a clear success ack before any ticket reminder. Resolve emails are not sent for issues fixed by troubleshooting alone. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-027: Multi-ticket tracking and already-resolved guard

**Status:** Accepted  
**Context:** Multi-ticket sessions needed reliable open-ticket lists, threaded resolution emails, and protection against resolving an already-closed ticket silently closing every remaining open ticket. Conversation summaries also dropped or duplicated ticket IDs because they only saw the mutable open list.  
**Decision:**  

- Track `dispatched_tickets` (open), `all_session_tickets` (append-only), and `ticket_email_ids` (Message-ID map).  
- If the operator names a `TKT-…` not in the open list, warn and do not bulk-resolve.  
- Summary injects all session tickets with OPEN/RESOLVED status.  
- Incident summary boundary uses `"escalation ticket"` so both critical and standard ticket messages close the prior incident window.  
**Consequences:** Safer multi-ticket resolve UX; accurate summaries; STEPS no longer bleed across incidents. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

---

## ADR-028: Portal-guided refunds (no agent-executed refund APIs)

**Status:** Accepted (Jul 13, 2026 — Brandon)  
**Context:** Backend refund APIs need many payment-gateway parameters; executing refunds from chat risks wrong-transaction refunds.  
**Decision:** Agent **guides** operators to submit refunds on the **SpyderWash portal**. Do **not** integrate `RefundEligibility` / `RefundProcessing` into the production agent path. Bible will contain refund-request instructions; Chetu does not invent KB content — gaps go back to Brandon.  
**Consequences:** `refund_request` intent routes to RAG/Bible portal guidance (not tool refund execute). Refund execute tools and mock `:8001` server removed from the repo. Read-only refund history via `ViewAllTransactionSearch` (`isRefund=true`) is still allowed. See [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md).

---

## ADR-029: Operator videos via Bible-section URL mapping (not transcript RAG)

**Status:** Proposed / preferred (awaiting Brandon video timeline)  
**Context:** ~24 YouTube operator videos. Transcript→LLM→semantic match is complex and costly.  
**Decision:** Prefer embedding each relevant **YouTube URL in the matching Bible/doc section** so ingest maps content → link (Option B). Do not build Whisper/transcript RAG for MVP. Timeline (all videos before UAT vs incremental) still TBD with Brandon.  
**Consequences:** Video answers depend on Bible/doc quality; no separate video pipeline until product confirms. See [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).

---

When making a significant architectural choice:

1. Add a numbered ADR to this file
2. Update [ROADMAP.md](ROADMAP.md) if it creates new tasks
3. Update [TECH_STACK.md](TECH_STACK.md) if stack changes

---

## ADR-030: Article-aware RAG ingestion with FlashRank reranking

**Status:** Accepted (Jul 18, 2026)  
**Context:** v2.2 KB document (324K chars) contains 171 structured articles with `ARTICLE START`/`ARTICLE END` delimiters, explicit metadata (ARTICLE ID, category, product, intent, search_terms), co-retrieval rules, and Brandon's own "Recommended RAG ingestion settings." The Bible (222K chars) is 82.5% brand-specific wiring/installation content that v2.2 explicitly excludes from the operator chatbot. Previous generic 500-char `RecursiveCharacterTextSplitter` destroyed article boundaries and mixed technician-only installation content into retrieval.  
**Decision:**

- **v2.2 articles as atomic chunks:** Regex-parse each article as one Document (~1550 chars avg). Extract ARTICLE ID, category, product, intent, search_terms, status, co_retrieval_ids into Chroma metadata fields.
- **Bible selective ingest:** Troubleshooting Sections 1-14 **plus** operator reference from `Operator Portal` through `Voiceover: SpyderWash Troubleshooting Guide` (Portal/POS/Kiosk/Hub FAQ, Installation FAQ including Relay vs Serial Control Board, Highest-Frequency Questions). Brand wiring diagrams, Voiceover transcript, PCI notes, and RMA SOP remain excluded. Tagged `source_priority=secondary`.
- **Section 0 → system prompt:** v2.2's "AI Retrieval and Response Rules" (17.8K chars) injected into the LLM system prompt, not stored as retrievable chunks.
- **FlashRank reranking:** MMR k=12 / fetch_k=40 / lambda=0.5; FlashRank `ms-marco-TinyBERT-L-2-v2` reranks to top 6 (supersedes earlier `rank-T5-flan` / top-4 settings — see ADR-032).
- **Co-retrieval:** 17 articles specify mandatory companion articles. After reranking, companion articles are fetched by `article_id` filter and prepended to context.
- **Metadata-aware filtering:** Narrow intents may map to v2.2 category for pre-filtering. **`technical_support` must not category-filter** (ADR-033). Direct `article_id` targeting supported.

**Consequences:** Respects Brandon's explicit RAG ingestion instructions while covering Intent Matrix instructional FAQs that live past the Installation heading. Eliminates technician-only wiring from retrieval. Requires `chroma_db/` deletion and re-ingest when upgrading. See [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).

---

## ADR-031: Human escalation is clarify-first (not outage workflow)

**Status:** Accepted (Jul 21, 2026)  
**Context:** Bare "I want to talk to support" / "I need a human agent" was entering `_ESCALATION_WORKFLOW_INTENTS`, which asked blast-radius questions or auto-created tickets with hallucinated issue context.  
**Decision:** Remove `escalation_request` from the outage workflow sets. Route to `human_escalation_clarify_node` first ("describe the issue…"). If the operator insists on a human without a new issue description, escalate cleanly. Post-escalation human-request phrases acknowledge the open ticket instead of re-entering RAG refusal.  
**Consequences:** Human-request phrases no longer trigger blast-radius or store-down SMS paths. Real outages still escalate via outage intents / `infer_blast_radius`.

---

## ADR-032: FlashRank model and wider retrieval window

**Status:** Accepted (Jul 21, 2026)  
**Context:** `rank-T5-flan` demoted correct operator chunks (e.g. Kiosk cashbox, receipt printer) and caused RAG refusals despite good MMR hits. Narrow top-4 also dropped usable companions.  
**Decision:** Use FlashRank `ms-marco-TinyBERT-L-2-v2` with MMR k=12 / fetch_k=40 and rerank top_k=6.  
**Consequences:** Better operator-FAQ precision. Model files live under `flashrank_cache/`. Re-test after model changes; wipe `__pycache__` and restart the app process.

---

## ADR-033: Do not category-filter `technical_support`

**Status:** Accepted (Jul 22, 2026)  
**Context:** `_INTENT_TO_CATEGORY_MAP` mapped `technical_support` → `"No Connection Error"`. Printer / Control Board / portal queries classified as `technical_support` retrieved only reader-connection articles, so the LLM correctly refused.  
**Decision:** Remove `technical_support` from the category filter map. Broad catch-all intents use unfiltered retrieval + FlashRank. Keep category filters only for narrow outage/kiosk/refund intents that map cleanly.  
**Consequences:** Receipt printer and similar RAG rows work without inventing dedicated intents. Slightly broader candidate pool; reranker must stay healthy (ADR-032).

---

## ADR-034: Domain-keyword safety net + content-based resolve prompt

**Status:** Accepted (Jul 20–22, 2026)  
**Context:** Router occasionally returned `out_of_domain` / `greeting` for in-domain SpyderWash phrasing (printer, portal login, static IP, cashbox). Intent-gated "Did this resolve?" missed many troubleshooting answers. Bare substring `"fixed"` false-triggered resolution on "fixed address".  
**Decision:** Expand `_DOMAIN_KEYWORDS` (printer/print/thermal, network/IP, login/password, cashbox/reconcile, etc.) to override false `out_of_domain`/`greeting`. Append "Did this resolve the issue? (Yes/No)" when answer content matches troubleshooting markers (≥2), not by intent alone. Resolution detection uses phrase-level matches, negation guard, and ≤8-word length guard.  
**Consequences:** Fewer false OOD refusals; resolve prompt appears on real step lists; Hub "fixed address" questions no longer short-circuit to "glad it's resolved".

---

## Related documents

- [PRD.md](PRD.md) — product scope
- [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) — vendor doc traceability
- [ROADMAP.md](ROADMAP.md) — implementation phases
- [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) — RAG ingest/retrieval current state
- [INTENT_MATRIX.md](INTENT_MATRIX.md) — router ↔ Brandon matrix
