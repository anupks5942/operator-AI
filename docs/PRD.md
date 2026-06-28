# Product Requirements Document — Operator Agent

**Product:** Setomatic / SpyderWash Operator AI  
**Scope:** Operator Agent only (Customer Agent is a separate future product)  
**Last updated:** July 2026  
**Documentation hub:** [docs/README.md](README.md) — full index of all docs and reading paths  
**Sources:** Client calls (Gregg, Brandon), [Brandon KB mail](../SendAnywhere_546287/Mail.pdf) ([BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md)), Intent Matrix, vendor [Requirement understanding](../SendAnywhere_546287/Requrement%20understading.docx) ([REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md)), [code status matrix](#feature-status-matrix)

---

## 1. Problem statement

Laundry operators need after-hours technical support for SpyderWash equipment, payments, and loyalty workflows. The Operator Agent answers from the knowledge base, calls live Setomatic APIs where appropriate, and escalates to human on-call staff when automated troubleshooting fails.

There is **no live human transfer** in the chat UI. Escalation means email and/or SMS to support/on-call, not a phone bridge.

---

## 2. Personas

| Persona | Needs |
|---------|-------|
| **Operator** | Troubleshoot machines, check loyalty/transactions, request refunds, report outages |
| **After-hours support** | Receive escalation email/SMS with conversation transcript |
| **On-call technician** | SMS alert for critical failures after troubleshooting fails |
| **Portal integrator (dev2 / frontend team)** | Stable REST API, session memory, operator contact fields |

---

## 3. Channels and scope

| Channel | Priority | Status |
|---------|----------|--------|
| .NET web chat (Super Admin portal) | P0 — **Production** | **Planned** — backend web chat UI not started; same API as QA |
| React web chat (QA / UAT) | P0 — QA only | **Partial** — dev2; hits `POST /api/v1/agent/chat` |
| Streamlit demo UI | Dev only | **Implemented** — local MVP, not deployable |
| Twilio voice call | P2 — deferred | **Deferred** — Phase 4 |
| SMS to operator | Escalation only | **Implemented** — outbound on-call SMS (not inbound operator SMS) |

---

## 4. Client rules (non-negotiable)

From Gregg (client call):

1. **Troubleshoot first** — For critical outage scenarios, provide KB troubleshooting steps before escalating.
2. **Escalate only on failure** — Do not dispatch on-call alerts until the operator confirms troubleshooting did not work.
3. **Blast-radius confirmation** — Ask whether one machine or the entire laundromat is affected before choosing the fix path.
4. **No live hardware status** — The agent must not claim real-time machine/port/hub telemetry. Direct operators to the official portal for live status.
5. **PCI DSS compliance (Gregg)** — Never collect, store, or transmit full payment card numbers (PAN), CVV/CVC, or track data in chat, logs, LLM prompts, or escalation channels. PAN is masked to last-4 at ingress; CVV/track requests are refused. See [src/utils/security.py](../src/utils/security.py) and [TESTING.md](TESTING.md#pci-compliance-checks).
6. **Beta before prod** — jQuery/.NET portal fixes are tested on beta before production (frontend team responsibility).

From Brandon ([Mail.pdf](../SendAnywhere_546287/Mail.pdf), [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md)):

1. **Escalation email template** — HTML template reviewed before production (feedback pending).
2. **Intent Matrix** — Each intent should map to escalation type: Email only, SMS only, Email+SMS, or None. **Not fully implemented** — see [INTENT_MATRIX.md](INTENT_MATRIX.md).
3. **KB Admin vision** — Upload/train from portal; operator feedback; AI-suggested chunk updates with admin approval; structured chunks with keywords — **Phase 5**, not in agent repo today.
4. **Bible** — Single ~500-page consolidated document (PDF preferred); weekly then ad-hoc updates until admin portal exists.

---

## 4b. Knowledge base strategy (SpyderWash Bible & videos)

Product direction (July 2026):

1. **The Bible of SpyderWash** — single KB document (**~500 pages** per Brandon mail) replacing legacy multi-manual `KB/` when delivered.
2. **Structured KB chunks** — Brandon prototype uses `chunk_id`, keywords, `common_queries` — target retrieval model; MVP uses generic splits — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md).
3. **Operator videos** — many guidance videos exist; hosting on **Rackspace** alongside SpyderWash frontend/backend is the recommended alignment.
4. **Agent consumption** — Bible text via RAG (PDF/DOCX ingest today); videos **not in RAG** until transcript or link strategy is chosen.
5. **Production gap** — files on cloud storage do not auto-index; needs ingest pipeline + shared vector DB (Phase 3); interim = email notify + manual re-index.

Full analysis: [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).

---

## 4c. Open product decisions (vendor doc gaps)

Confirm with product before Phase 2+. Traceability: [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md).

| Topic | MVP default | Status |
|-------|-------------|--------|
| **Bible embedded images** | Text captions in source doc; text-only RAG ingest | **Decision pending** — OCR / figure links / multimodal Phase 2+ |
| **Operator videos** | Bible text first; videos in portal only | **Decision pending** — see [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| **Bilingual (English/Spanish)** | English-only prompts and responses | **Deferred** until product confirms operator need |
| **Low-confidence AI escalation** | Not used — Gregg troubleshoot-first + Intent Matrix routing instead | **By design** — ADR-014 |

---

## 5. Core user journeys

### 5.1 General troubleshooting (RAG)

**Trigger:** Operator asks how to fix a machine, kiosk, or configuration issue.  
**Flow:** Router → RAG node → answer with KB sources.  
**Acceptance:** Answer cites manual content; admits when KB lacks information.

### 5.2 Loyalty / transactions / refunds (tools)

**Trigger:** Balance lookup, transaction history, refund request, global system status.  
**Flow:** Router → tool node (ReAct loop) → live Setomatic API or mock refund API.  
**Acceptance:** Refund workflow is sequential: history → eligibility → execute (never skip eligibility).

### 5.3 Outage workflow (Gregg TC1 / TC2)

**Trigger:** Machine down, store down, kiosk frozen, multiple machines offline, human escalation request.

**Flow:**

```
Report issue → Blast-radius question → KB troubleshooting → "Did this resolve?" →
  Yes → Close politely
  No  → Dispatch escalation (email + SMS today; per-intent channels Phase 2)
```

**Acceptance criteria:**

| Test | Steps | Expected outcome |
|------|-------|------------------|
| **TC1** | Washer won't start → one machine → Yes, fixed | Blast-radius asked; hub/KB steps; polite close; **no** escalation |
| **TC2** | (after TC1 in same session) Everything down → No, still offline | Troubleshoot first; then ticket + email/SMS; summary reflects **current** incident |
| **Post-escalation** | "wait yes" / "resolved" | Ack ticket already sent; do **not** restart blast-radius workflow |

Automated coverage: [tests/test_outage_workflow.py](../tests/test_outage_workflow.py)

### 5.4 Hardware status guardrail

**Trigger:** "Is port 4 offline?", "Is washer #5 running?"  
**Flow:** Router → guardrail node → static refusal directing to operator portal.  
**Acceptance:** No API call, no fabricated live status.

### 5.5 Out-of-domain / prompt injection

**Trigger:** Unrelated topics or instruction override attempts.  
**Flow:** Router → static refusal node.  
**Acceptance:** No LLM answer, no tools.

---

## 6. API requirements (frontend integration)

**Canonical endpoint:** `POST /api/v1/agent/chat` on port 8000 — see [API.md](API.md).

| Field | Required | Purpose |
|-------|----------|---------|
| `operator_id` | Yes | **Target:** scopes Setomatic API tool calls. **Today:** accepted on API and stored in state, but [tools.py](../src/agent/tools.py) still hardcodes `OperatorId=4` — fix in Phase 1 |
| `session_id` | Yes | LangGraph thread memory (stable per chat session) |
| `message` | Yes | Operator's plain-text input |
| `operator_name` | No | Escalation email (defaults to "Unknown Operator" if omitted) |
| `operator_email` | No | Escalation email |
| `operator_phone` | No | Escalation email |

**Auth:** No JWT or API-key validation on the agent API today. .NET portal auth contract is **not defined** — backend has not started web chat UI. React QA can pass fields manually until Phase 2.

**Response fields:** `reply`, `detected_intent`, `requires_escalation` (true when email/SMS dispatched this turn).

---

## 7. Feature status matrix

| Capability | Status | Primary code |
|------------|--------|--------------|
| PCI PAN masking + CVV refusal | **Implemented** | [security.py](../src/utils/security.py), [graph.py](../src/agent/graph.py), [tests/test_security.py](../tests/test_security.py) |
| Outage workflow TC1/TC2 | **Implemented** + tested | [src/agent/graph.py](../src/agent/graph.py), [tests/test_outage_workflow.py](../tests/test_outage_workflow.py) |
| RAG over KB (Chroma) | **Partial** — legacy `KB/`; Bible pending | [src/services/rag_service.py](../src/services/rag_service.py) |
| SpyderWash Bible as sole KB | **Planned** | ~500 pages (Brandon mail); manual ingest when ready |
| Structured KB chunks + admin feedback loop | **Planned** | Phase 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Bible images in RAG | **Not implemented** | Text-only ingest — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| Bilingual (English/Spanish) | **Deferred** | Decision pending — [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) |
| Video content in agent | **Not implemented** | Strategy TBD — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| Rackspace KB/video hosting + ingest | **Planned** | Phase 3 — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| Live loyalty / transactions | **Implemented** | [src/agent/tools.py](../src/agent/tools.py) |
| Refunds (mock or live) | **Partial** — mock only in practice | Beta refund APIs **not ready**; keep `USE_MOCK_REFUNDS=true` |
| Global system status scrape | **Implemented** | [src/agent/tools.py](../src/agent/tools.py) |
| Production REST API | **Implemented** | [src/api/server.py](../src/api/server.py) |
| Live escalation email (Mandrill) | **Implemented** | [src/services/notifications.py](../src/services/notifications.py) |
| Live escalation SMS (Twilio) | **Implemented** | [src/services/notifications.py](../src/services/notifications.py) |
| Per-intent Email vs SMS routing | **Planned** | Sends both on every escalation today |
| Operator contact from portal auth | **Partial** | API accepts fields; Streamlit does not pass them |
| React QA chatbot (UAT only) | **Partial** | dev2 — in progress |
| .NET Super Admin widget (prod) | **Planned** | Setomatic frontend — not started |
| `operator_id` wired to Setomatic tools | **Planned** | Phase 1 — hardcoded `4` today |
| Twilio voice | **Deferred** | Phase 4 in [ROADMAP.md](ROADMAP.md) |
| Qdrant / managed vector DB | **Deferred** | Phase 3 |
| KB admin dashboard (feedback, chunk editor, pending updates) | **Deferred** | Phase 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Customer Agent | **Deferred** | Separate product |

---

## 8. Open blockers (June 2026)

| Item | Owner | Notes |
|------|-------|-------|
| Beta refund APIs | Setomatic backend | Not ready — mock server required — [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) |
| .NET auth → agent API | Setomatic backend | Web chat UI not started |
| Production hosting target | infra vendor + product | **Rackspace preferred** — see [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| Escalation email template sign-off | Product owner | Feedback pending |
| Bible PDF delivery | Product owner | ~500 pages; blocks RAG cutover |
| Bible image strategy (captions vs OCR vs links) | Product + dev1 | Text-only RAG today |
| Bilingual support | Product | Vendor doc mentions; not in code |
| Video strategy (transcripts vs links) | Product + dev1 | Blocks video-aware answers |

Full phase owners: [ROADMAP.md](ROADMAP.md).

---

## 9. Out of scope (v1 production)

- Customer-facing agent (end-user laundromat customers)
- Live machine/port/hub telemetry in chat
- Real-time voice in web chat (REST-only for text)
- KB upload UI (manual `KB/` folder + re-ingest until Bible + Rackspace pipeline)
- Video ingestion / transcription in agent (until strategy approved)
- Bible image OCR / multimodal RAG (until strategy approved)
- Bilingual operator support (until product confirms)
- Immediate on-call **phone call** (SMS/email only)
- Customer Agent (separate product — vendor dual-agent vision)
- Live call transfer to human (vendor § Human Escalation)

---

## 10. Success metrics (suggested)

| Metric | Target |
|--------|--------|
| TC1/TC2 automated tests | Pass on every PR |
| Escalation false-positive rate | Zero tickets without troubleshooting attempt (except `critical_outage`) |
| API p95 latency | Under 10s (warning threshold already logged in server) |
| KB answer grounding | Sources cited in outage troubleshooting responses |

---

## 11. Documentation map

**Full index (all 17 docs + reading paths):** [README.md](README.md)

Use this section for quick navigation from the PRD. Do not duplicate the README table here — update the hub when adding docs.

### Product & delivery

| Doc | When to read |
|-----|--------------|
| [PRD.md](PRD.md) | Requirements, client rules, [feature status](#feature-status-matrix) — **you are here** |
| [ROADMAP.md](ROADMAP.md) | Phases 0–5, blockers, production-readiness gaps, owners |
| [INTENT_MATRIX.md](INTENT_MATRIX.md) | Brandon 29-row matrix → router intents and escalation targets |

### Client & external requirements

| Doc | Source | When to read |
|-----|--------|--------------|
| [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) | `Requrement understading.docx` | Vendor dual-agent vision vs this repo |
| [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) | `API_Requirements.docx` | Setomatic POS APIs (loyalty, refunds) — Sprint 1 blockers |
| [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) | `Mail.pdf` + screenshots | Bible ~500 pp, KB Admin prototype, chunk map |
| [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) | Product + planning | Bible/images/videos, Rackspace ingest strategy |

### Integrators (dev2 / .NET)

| Doc | When to read |
|-----|--------------|
| [API.md](API.md) | `POST /api/v1/agent/chat` contract, CORS, examples |
| [ENVIRONMENT.md](ENVIRONMENT.md) | Env vars for agent, Setomatic, Twilio, Mandrill |
| [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) | Multi-turn outage UX (Gregg TC1/TC2) |

### Engineering

| Doc | When to read |
|-----|--------------|
| [CODEBASE.md](CODEBASE.md) | What each repo file does |
| [ARCHITECTURE.md](ARCHITECTURE.md) | LangGraph, RAG path, two-server model |
| [TECH_STACK.md](TECH_STACK.md) | MVP vs production stack |
| [DECISIONS.md](DECISIONS.md) | Locked ADRs (scope, API, Chroma, Brandon chunks, etc.) |
| [ONBOARDING.md](ONBOARDING.md) | Guided tour for new backend devs |
| [TESTING.md](TESTING.md) | Unit tests, manual TC1/TC2, PCI checks |
| [RUNBOOK.md](RUNBOOK.md) | Local dev terminals, demo prep, failures |

### Common questions → doc

| Question | Go to |
|----------|-------|
| Is feature X built? | [§7 Feature status matrix](#feature-status-matrix) + [ROADMAP.md](ROADMAP.md) |
| What blocks production? | [ROADMAP.md](ROADMAP.md) — production readiness + gap register |
| Which API does React call? | [API.md](API.md) |
| Which APIs does Setomatic backend owe us? | [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) |
| SMS-only for store-down? | [INTENT_MATRIX.md](INTENT_MATRIX.md) |
| How does outage escalation work? | [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) |
| Bible size, images, admin portal? | [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md), [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
