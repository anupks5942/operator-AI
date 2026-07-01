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
**Decision:** Production integrators use **`POST /api/v1/agent/chat`** on [server.py](../src/api/server.py) only.  
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

## ADR-010: Mock server on :8001 for refund development

**Status:** Accepted  
**Context:** Setomatic refund APIs may be unavailable or risky during early dev.  
**Decision:** [mock_server.py](../src/api/mock_server.py) on port **8001** simulates loyalty/transaction/refund endpoints when `USE_MOCK_REFUNDS=true`.  
**Consequences:** Two processes in local dev when testing refunds. Port 8001 loyalty/transaction routes are unused by tools — only refund endpoints are called. See [ARCHITECTURE.md](ARCHITECTURE.md).

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

**Status:** Accepted (planning)  
**Context:** Product owner is compiling “The Bible of SpyderWash” (~500 pages per Brandon mail) as the only Operator Agent KB. Operator guidance videos will exist separately. Planning recommends hosting Bible and videos on Rackspace alongside SpyderWash frontend/backend. Brandon’s KB Admin prototype defines structured chunks and feedback loop — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md).  
**Decision:** **Target:** single Bible document for RAG; legacy multi-manual `KB/` is interim only. Rackspace Cloud Files for Bible + video assets; agent consumes via **ingest pipeline → shared vector DB**, not direct filesystem reads in production. Videos require a separate strategy (transcripts in RAG vs portal links only) — not in MVP code.  
**Consequences:** Manual `KB/` ingest OK for demo. Production needs Phase 3 ingest + Qdrant + Rackspace deploy. See [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).

---

## ADR-015: Structured KB chunks vs generic RAG splits

**Status:** Accepted (planning)  
**Context:** Brandon’s [Mail.pdf](../SendAnywhere_546287/Mail.pdf) and local KB Admin prototype use **structured chunks** (`chunk_id`, `section_id`, `keywords`, `common_queries`) for retrieval and human-in-the-loop updates. Current [rag_service.py](../src/services/rag_service.py) uses **500-char RecursiveCharacterTextSplitter** on PDF/DOCX with filename metadata only.  
**Decision:** **MVP:** generic splits acceptable for demo/UAT with manually loaded Bible. **Target (Phase 1–5):** migrate toward Brandon chunk schema or section-aware splits; KB Admin approve workflow before applying AI-suggested updates. Intent Matrix remains the **routing/escalation** layer; chunks are the **retrieval** layer — see [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md).  
**Consequences:** Do not conflate router intents with `sw_*` chunk IDs. Phase 5 builds admin UI + feedback loop; interim = email notification + manual re-ingest.

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

When making a significant architectural choice:

1. Add a numbered ADR to this file
2. Update [ROADMAP.md](ROADMAP.md) if it creates new tasks
3. Update [TECH_STACK.md](TECH_STACK.md) if stack changes

---

## Related documents

- [PRD.md](PRD.md) — product scope
- [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) — vendor doc traceability
- [ROADMAP.md](ROADMAP.md) — implementation phases
