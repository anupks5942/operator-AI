# Requirements Traceability Map

Maps the vendor **Requirement understanding** document (`SendAnywhere_546287/Requrement understading.docx`) to this repo’s **Operator Agent** scope, code, and phased roadmap.

**Last updated:** July 2026

**How to read this doc:** The vendor document describes a **~6-month dual-agent platform** (Customer + Operator, voice, gateway, admin panel). This repo implements **Operator Agent only** — an annotated subset with honest status labels. Do not treat vendor deliverables as implemented unless marked **Implemented** here.

Status labels: **Implemented** | **Partial** | **Planned** | **Deferred** | **Out of scope** | **N/A** (Customer Agent / not in this repo)

Full product rules: [PRD.md](PRD.md). Phased work: [ROADMAP.md](ROADMAP.md). Locked choices: [DECISIONS.md](DECISIONS.md).

---

## Vendor timeline → repo phases

| Vendor doc phase | Duration (vendor) | Repo phase | Notes |
|------------------|-------------------|------------|-------|
| Requirement & Design | 2 weeks | Phase 0 | Architecture + Intent Matrix in repo |
| Customer Agent (SMS + Web Chat) | 14 weeks | **N/A** | Separate product — not this repo |
| UAT & Pilot Launch | 2 weeks | Phase 0–1 | TC1/TC2 + React QA |
| Voice + Operator Agent | 10 weeks | Phase 1–4 | Operator web chat now; voice Phase 4 |
| Advanced Features | 4 weeks | Phase 5 | Analytics, outbound messaging, A/B |

**Priority note (vendor doc):** “Priority Operational agent” = Operator Agent — that is **this repo**.

---

## Intentional differences (product decisions)

These are **deliberate** gaps vs the vendor end-state doc — not oversights.

| Vendor doc says | This repo / PRD says | ADR |
|-----------------|----------------------|-----|
| Dual-agent (Customer + Operator) | **Operator Agent only** | ADR-001 |
| Live call transfer / human handoff in channel | **Email + SMS only** — no phone bridge | ADR-014 |
| API Gateway (JWT/Auth0) on agent | Auth at gateway — **not on agent yet** (Phase 2) | ADR-014 |
| AWS / Azure hosting | **Rackspace preferred** (SpyderWash already there) | ADR-013 |
| SendGrid / AWS SES email | **Mandrill SMTP** (implemented) | — |
| Pinecone or pgvector | **Chroma MVP → Qdrant** target | ADR-003 |
| Low-confidence AI → escalate | **Intent Matrix + troubleshoot-first** (Gregg/Brandon) | ADR-014 |
| Inbound operator SMS channel | **Outbound escalation SMS only** | PRD §3 |
| Custom JS chat widget | **React QA + .NET Super Admin** — same REST API | ADR-006 |

---

## Section 1 — Project summary (dual-agent vision)

| Requirement | Status | Repo evidence / notes |
|-------------|--------|-------------------------|
| Customer Agent (24/7, bilingual, POS) | **N/A** | Out of scope — [PRD.md](PRD.md) §9 |
| Operator Agent (24/7, KB-driven) | **Partial** | LangGraph + RAG + tools + escalation MVP |
| POS / Setomatic API integration | **Partial** | Sprint 1 blockers — [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) |
| ~6 month full dual-agent timeline | **Planned** | Mapped to Phase 0–5 — not a committed calendar in this repo |

---

## Section 2 — High-level architecture (8 layers)

| Layer (vendor) | Status | Repo phase | Notes |
|----------------|--------|------------|-------|
| 1. Multi-channel input (Voice, SMS, Web) | **Partial** | 0–4 | Web REST chat only; voice Phase 4; SMS outbound escalation |
| 2. API Gateway (JWT, rate limit, routing) | **Planned** | 2 | No auth on [server.py](../src/api/server.py) today |
| 3. Dual AI agent core | **Partial** | — | Operator only; OpenAI not Claude; English only today |
| 4. Intelligence layer (RAG, LangGraph, memory) | **Partial** | 1–3 | Chroma + MemorySaver; Qdrant + durable checkpoints Phase 3 |
| 5. Multi-tenant backend (PostgreSQL, analytics) | **Deferred** | 3–5 | No conversation DB; in-memory sessions |
| 6. Integrations (Twilio, POS, email) | **Partial** | 0–2 | Twilio + Mandrill + Setomatic beta APIs |
| 7. Admin panel (FAQ editor, escalation rules) | **Deferred** | 5 | Super Admin KB upload planned by backend team |
| 8. Human escalation (live transfer, tickets) | **Partial** | 0–2 | Ticket ID + email/SMS + transcript — **no live transfer** |

---

## Section 3 — Workflow development strategy (Steps 1–8)

| Step (vendor) | Status | Notes |
|---------------|--------|-------|
| 1. Requirement analysis (POS, channels, personas) | **Partial** | Gregg/Brandon rules in PRD; POS gaps in `API_Requirements.docx` |
| 2. Design architecture | **Partial** | [ARCHITECTURE.md](ARCHITECTURE.md) — MVP not full 8-layer |
| 3. Implement core AI agents | **Partial** | Operator web path only; Customer Agent N/A |
| 4. Integrate channels | **Partial** | Web chat API ready; voice/SMS-inbound deferred |
| 5. Backend & admin panel | **Deferred** | Phase 5 |
| 6. Orchestration & RAG pipeline | **Partial** | LangGraph done; continuous ingest Phase 3+ |
| 7. Testing & pilot | **Partial** | Automated TC1/TC2; React pilot Phase 0–1 |
| 8. Voice & advanced features | **Deferred** | Phase 4–5 |

---

## Section 4 — Tools and technology

| Tool (vendor) | Status | Repo choice |
|---------------|--------|-------------|
| Twilio Voice & SMS | **Partial** | SMS escalation implemented; voice Phase 4 |
| Custom / embedded web chat | **Partial** | `POST /api/v1/agent/chat` — [API.md](API.md) |
| JWT / Auth0 | **Planned** | Phase 2 — blocked on .NET contract |
| GPT-4o / Claude 3.5 | **Partial** | `gpt-4o-mini` default — [config.py](../src/config.py) |
| Pinecone / Qdrant / pgvector | **Partial** | Chroma now; Qdrant Phase 3 |
| LangChain / LangGraph | **Implemented** | [graph.py](../src/agent/graph.py) |
| Python / FastAPI | **Implemented** | [server.py](../src/api/server.py) |
| PostgreSQL multi-tenant | **Deferred** | Phase 3 checkpoints + Phase 5 analytics |
| React admin panel | **Deferred** | Phase 5 — distinct from dev2 React QA chat |
| AWS / Azure | **Planned** | Rackspace preferred — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| Datadog / CloudWatch | **Planned** | Basic structured logs today; shipping Phase 2–3 |
| SendGrid / AWS SES | **Partial** | Mandrill for escalation email |

---

## Operator Agent checklist (vendor doc § “Priority Operational agent”)

### 1. Knowledge & content

| Requirement | Status | Notes |
|-------------|--------|-------|
| Manuals, troubleshooting, error codes, release notes | **Partial** | Legacy `KB/`; Bible ~500 pp — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Structured KB chunks + admin feedback | **Planned** | Brandon prototype — Phase 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Digitized PDF/DOCX for ingestion | **Partial** | [rag_service.py](../src/services/rag_service.py) — PDF/DOCX only |
| XLSX / web pages | **Out of scope (v1)** | Not in loader — convert or extend loader |
| Versioning of manuals | **Planned** | Phase 5 |
| RAG preprocessing + embeddings | **Implemented** | HuggingFace + Chroma |
| Vector DB | **Partial** | Chroma MVP; Qdrant Phase 3 |
| Continuous ingestion pipeline | **Planned** | Phase 3 Rackspace → ingest job |
| **Bible embedded images** | **Planned** | Text-only ingest today — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) § Bible images |
| Operator videos | **Planned** | Strategy TBD — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |

### 2. Technical & system

| Requirement | Status | Notes |
|-------------|--------|-------|
| LLM with tool calling | **Implemented** | OpenAI via LangGraph |
| **Bilingual (English/Spanish)** | **Deferred** | **Decision pending** — see [PRD.md](PRD.md) §4c |
| LangGraph orchestration | **Implemented** | |
| Dedicated phone line (Twilio Voice + STT) | **Deferred** | Phase 4 |
| Operator portal web chat | **Partial** | API ready; .NET widget not started |
| Conversation history / session metadata store | **Partial** | MemorySaver — not durable |
| Multi-tenant operators | **Deferred** | Phase 5 |

### 3. Operational

| Requirement | Status | Notes |
|-------------|--------|-------|
| Escalation policies | **Partial** | Gregg troubleshoot-first; Brandon per-intent channels Phase 2 |
| Transcript + summary on handoff | **Implemented** | [notifications.py](../src/services/notifications.py) |
| **Low-confidence → escalate** | **Deferred** | Replaced by intent + confirmation workflow — ADR-014 |
| Monitoring dashboard (volume, resolution, escalations) | **Deferred** | Phase 5; basic API latency logs today |
| Pilot with few operators | **Planned** | Phase 1 React QA / UAT |

### 4. Setup & maintenance

| Requirement | Status | Notes |
|-------------|--------|-------|
| Admin portal KB upload | **Deferred** | Phase 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Continuous learning / feedback loop | **Planned** | Brandon KB Admin — Phase 5 |
| POS / internal tool API integration | **Partial** | Setomatic loyalty/transactions/refunds |

---

## Client preparation checklist (vendor doc § checklist 1–8)

| # | Checklist item | Status | Repo phase |
|---|----------------|--------|------------|
| 1 | KB preparation (manuals, FAQs, intents) | **Partial** | Bible + Intent Matrix |
| 2 | RAG pipeline + vector DB + update process | **Partial** | Manual ingest; auto Phase 3 |
| 3 | AI & orchestration (LLM, persona, LangGraph) | **Partial** | Persona in router/RAG prompts |
| 4 | Multi-channel (phone + web chat) | **Partial** | Web only until Phase 4 |
| 5 | Multi-tenant backend + logging | **Deferred** | Phase 3–5 |
| 6 | Escalation rules + transcript capture | **Partial** | Transcript yes; rules Phase 2 |
| 7 | Testing & pilot | **Partial** | Unit tests done; React pilot open |
| 8 | Maintenance & metrics | **Deferred** | Phase 5 |

---

## Open product decisions (not in vendor doc — confirm with client)

| Topic | Options | Default for MVP | Doc |
|-------|---------|-------------------|-----|
| **Bible images** | Text captions / OCR at ingest / figure links / multimodal RAG | Text captions + manual ingest | [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| **Operator videos** | Transcripts / link-only / defer | Defer (Bible text first) | [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| **Bilingual operators** | English-only / Spanish prompts / detect language | **English-only** until product confirms | [PRD.md](PRD.md) §4c |
| **Low-confidence escalation** | LLM confidence score / intent-only (current) | Intent + Gregg workflow | ADR-014 |

---

## Maintenance

When the vendor requirements doc or client scope changes:

1. Update this map (status column).
2. Update [PRD.md](PRD.md) feature matrix if product scope shifts.
3. Add an ADR in [DECISIONS.md](DECISIONS.md) for intentional divergences.
4. Add or re-phase tasks in [ROADMAP.md](ROADMAP.md).

---

## Related documents

- [PRD.md](PRD.md) — Operator Agent requirements
- [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) — Brandon mail, KB Admin prototype
- [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) — Setomatic POS APIs (`API_Requirements.docx`)
- [ROADMAP.md](ROADMAP.md) — phased backlog
- [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) — Bible, images, videos, Rackspace
- [DECISIONS.md](DECISIONS.md) — ADR-001, ADR-013, ADR-014
