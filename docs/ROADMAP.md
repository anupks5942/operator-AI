# Roadmap — Operator Agent to Full Production

Phased task backlog. Check items off as completed. Each phase builds on the previous.

**Team labels:** **dev1** = backend / agent repo. **dev2** = React QA UI. **infra vendor** = deployment, Rackspace, vector DB (Phase 3+).

**Last updated:** July 2026 (includes production-readiness audit)

---

## Production readiness status

**Verdict: not production-ready.** Suitable for **local demo**, **internal QA**, and **controlled single-instance UAT** behind a trusted gateway. Not ready for internet-facing or multi-replica production.

| Environment | Ready? | Notes |
|-------------|--------|-------|
| Local demo / Streamlit | **Yes** | In-process graph; not deployable |
| React QA → single `:8000` instance | **Partial** | No auth; mock refunds default; sessions in-memory |
| Client demo (outage + escalation) | **Partial** | Configure live notifications + client escalation recipients |
| UAT with live refunds | **No** | Beta refund APIs blocked; `USE_MOCK_REFUNDS=true` default |
| Multi-replica / Rackspace prod | **No** | MemorySaver, local Chroma, no deploy artifacts |

### What is solid today (MVP)

- Gregg outage workflow (blast-radius → troubleshoot → confirm → escalate) + TC1/TC2 unit tests
- PCI: PAN masking at ingress; CVV/track guardrail; outbound masking on escalation
- Canonical API: `POST /api/v1/agent/chat` with telemetry middleware
- Feature-flagged live Mandrill email + Twilio SMS
- Tool HTTP timeouts and Pydantic input validation on Setomatic calls

---

## Team ownership

| Phase | Owner | Scope |
|-------|-------|-------|
| **0** (demo) | **dev1** | Escalation workflow, tests, live notifications, demo prep |
| **1** (QA/UAT integration) | **dev1** | API hardening, React QA integration, mock refunds until backend ready |
| **2** (pre-production) | **dev1** | Intent Matrix escalation routing, auth hookup, CI, legacy cleanup |
| **3** (production infra) | **infra vendor** | Docker, Rackspace deploy, load test, secret store, multi-replica |
| **4+** (voice, platform) | **infra vendor + product** | Twilio voice, KB admin, video/transcript pipeline |

### UI channels

| UI | Environment | Owner | Integration |
|----|-------------|-------|-------------|
| **Streamlit** | Local dev only | dev1 | In-process graph — not deployable |
| **React chatbot** | **QA / UAT only** | dev2 | `POST :8000/api/v1/agent/chat` |
| **.NET widget** | **Production** | Setomatic frontend team | SpyderWash Super Admin portal → same API |

Both production and QA UIs must call the **same** agent API ([`server.py`](../src/api/server.py) on `:8000`). React is not the production widget. Production deploys **`server.py` only** — not `main.py` / legacy `/query` or `/notify/*`.

### External reference

Vendor SOW (RAG platform, POS integrations, multi-channel, voice, admin portal) complements this repo roadmap. Align during Phase 1 kickoff.

KB / Bible / Brandon KB Admin: [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md), [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md).

POS / Setomatic backend APIs: [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) — final scope: 7 APIs (4 core + 3 future platform).

---

## Gap register (production audit)

Gaps from codebase audit, mapped to phases. Severity = impact if shipped to prod without fix.

### Critical — must fix before production

| Gap | Phase | Owner | File / area |
|-----|-------|-------|-------------|
| No API authentication or authorization | 2 | dev1 + .NET team | [server.py](../src/api/server.py) |
| `operator_id` hardcoded `4` in tool HTTP calls | 1 | dev1 | [tools.py](../src/agent/tools.py) |
| `USE_MOCK_REFUNDS` defaults `true` | 1–2 | dev1 | [config.py](../src/config.py) — fail fast in prod |
| `MemorySaver` — sessions lost on restart, not shared across replicas | 3 | infra vendor | [graph.py](../src/agent/graph.py) |
| Local Chroma `./chroma_db` — not multi-replica safe | 3 | infra vendor | [rag_service.py](../src/services/rag_service.py) |
| No Dockerfile / CI pipeline | 2–3 | dev1 + infra vendor | repo root |
| Legacy `/notify/sms` and `/notify/email` unauthenticated if `main.py` deployed | 2 | dev1 | [routes.py](../src/api/routes.py) — remove or gate |
| Client-supplied `session_id` with no auth binding | 2 | dev1 | [server.py](../src/api/server.py) |

### Major — required for GA or reliable UAT

| Gap | Phase | Owner | File / area |
|-----|-------|-------|-------------|
| Intent Matrix escalation channels (SMS-only store-down, etc.) | 2 | dev1 | [notifications.py](../src/services/notifications.py) |
| Missing router intents (receipt printer, recharge failure) | 2 | dev1 | [router.py](../src/agent/router.py) |
| No HTTP integration tests for `/api/v1/agent/chat` | 1 | dev1 | [tests/](../tests/) |
| `troubleshoot_first_node` creates new `RAGService()` per turn | 1 | dev1 | [graph.py](../src/agent/graph.py) — reuse singleton from [nodes.py](../src/agent/nodes.py) |
| Sync blocking `chat()` handler; heavy cold start (torch, embeddings) | 2–3 | dev1 + infra vendor | [server.py](../src/api/server.py), startup pre-warm |
| Shallow `/health` — no dependency readiness | 2 | dev1 | Add `/ready` (OpenAI, Chroma, Setomatic) |
| 500 responses leak internal exception text | 2 | dev1 | [server.py](../src/api/server.py) |
| No rate limiting or `message` max length | 2 | dev1 | FastAPI middleware |
| KB: `.txt` not ingested; Bible not integrated | 1–3 | dev1 | [rag_service.py](../src/services/rag_service.py), [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| Escalation not idempotent on client retry | 2 | dev1 | [graph.py](../src/agent/graph.py) |
| PCI: mock notification paths log full SMS body | 2 | dev1 | [notifications.py](../src/services/notifications.py) |

### Minor — polish and ops hygiene

| Gap | Phase | Owner | Notes |
|-----|-------|-------|-------|
| `print()` in mock notification path | 2 | dev1 | Logger only |
| No `.env.example` in repo | 1 | dev1 | Document all vars from [ENVIRONMENT.md](ENVIRONMENT.md) |
| Project version `0.1.0` / prototype naming | 2 | dev1 | [pyproject.toml](../pyproject.toml) |
| CORS includes localhost origins | 2 | dev1 | Env-gate for prod |
| No structured JSON log shipping | 2–3 | infra vendor | Datadog / CloudWatch / Loki |
| No circuit breakers for OpenAI / Setomatic outages | 3 | dev1 | Retries + degraded responses |
| Mock server `:8001` must never be exposed in prod | 3 | infra vendor | Network policy |

---

## Known blockers (July 2026)

| Blocker | Status | Impact | Workaround |
|---------|--------|--------|------------|
| **Refund APIs on beta** (`RefundEligibility` + `RefundProcessing`) | Not ready (Setomatic backend) | Only 2 of 4 core agent APIs remain; cannot flip `USE_MOCK_REFUNDS=false` | Keep mock server on `:8001` — [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) |
| **.NET auth contract** | Not started (web chat UI not begun) | No JWT/API-key for `operator_id` + contact fields | dev2 passes fields manually; auth Phase 2 |
| **Production hosting** | Rackspace preferred; not deployed | Phase 3 | See [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| **`operator_id` in tools** | API accepts field; tools hardcode `4` | Wrong operator scope in prod | Wire `state.operator_id` — Phase 1 |
| **Bible partially ready** | Brandon confirmed 250 pages done; sending PDF | RAG still on legacy `KB/` | Manual ingest when PDF received — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| **Video strategy undecided** | Transcripts vs links vs defer | Videos not in RAG | [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |

---

## Phase 0 — Demo-ready (current)

**Goal:** Demo with Gregg TC1/TC2 and live escalation path.  
**Owner:** dev1

| Status | Task | Notes |
|--------|------|-------|
| [x] | Gregg escalation workflow (blast-radius → troubleshoot → confirm → escalate) | [graph.py](../src/agent/graph.py) |
| [x] | Automated TC1/TC2 tests | [tests/test_outage_workflow.py](../tests/test_outage_workflow.py) |
| [x] | Live email + SMS escalation (`USE_LIVE_NOTIFICATIONS`) | [notifications.py](../src/services/notifications.py) |
| [x] | Intent Matrix documented in repo | [INTENT_MATRIX.md](INTENT_MATRIX.md) |
| [x] | PCI hardening (ingress mask, CVV guardrail, outbound mask, tests) | [tests/test_security.py](../tests/test_security.py) |
| [ ] | Revert `.env` escalation recipients for demo | `ESCALATION_EMAIL`, `ESCALATION_SMS_TO` |
| [ ] | dev2 React → `POST /api/v1/agent/chat` with operator contact fields | [API.md](API.md) |
| [ ] | Manual TC1/TC2 smoke on React (not just Streamlit) | [TESTING.md](TESTING.md) |
| [ ] | Escalation email template sign-off incorporated | HTML in [notifications.py](../src/services/notifications.py) |

**Exit criteria:** TC1/TC2 pass in React against `:8000`; demo uses production escalation recipients.

---

## Phase 1 — QA / UAT integration

**Goal:** React QA widget integrated; agent API ready for .NET prod widget; close critical data-scope gaps.  
**Owner:** dev1 (backend); dev2 (React QA UI)

| Status | Task | Notes |
|--------|------|-------|
| [ ] | Wire `state.operator_id` into Setomatic tool API calls (remove hardcoded `4`) | **Critical** — [tools.py](../src/agent/tools.py) |
| [ ] | dev2: React passes `operator_id`, `operator_name`, `operator_email`, `operator_phone` | [API.md](API.md) |
| [ ] | CORS allow QA React origin if needed | [server.py](../src/api/server.py) |
| [ ] | API integration tests (HTTP `/chat` via `TestClient`) | Schema, CORS, error shapes — no graph-only coverage |
| [ ] | Reuse `get_rag_service()` in `troubleshoot_first_node` (stop per-turn `RAGService()`) | **Major perf** — [graph.py](../src/agent/graph.py) |
| [ ] | Add `.env.example` (no secrets) | [ENVIRONMENT.md](ENVIRONMENT.md) |
| [ ] | Enforce canonical `/api/v1/agent/chat` only | Deprecate `/query` in docs |
| [ ] | Set `USE_MOCK_REFUNDS=false` against beta Setomatic APIs | **Blocked** until backend ready |
| [ ] | Manual ingest SpyderWash Bible when PDF/DOCX delivered; RAG quality test | [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| [ ] | Product decision: Bible **images** (captions vs OCR vs links) | [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) |
| [ ] | Product decision: **bilingual** (English/Spanish) — in or out of scope | [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) |
| [ ] | Optional: Streamlit calls `:8000` instead of in-process graph | Telemetry parity |

**Exit criteria:** React QA passes TC1/TC2 against `:8000` with real operator contact in escalation emails; tools use request `operator_id`; HTTP tests green.

**Minimum UAT bar (single instance, behind gateway):** Phase 0 exit + Phase 1 `operator_id` wiring + validated refund flag + persistent `chroma_db` volume or pre-built index.

---

## Phase 2 — Pre-production hardening

**Goal:** Intent Matrix compliance, security, CI, legacy cleanup — required before GA.  
**Owner:** dev1

| Status | Task | Notes |
|--------|------|-------|
| [ ] | Intent Matrix: Email-only vs SMS-only vs both vs none | SMS-only for store-down — [INTENT_MATRIX.md](INTENT_MATRIX.md) |
| [ ] | Tests for SMS-only and Email-only escalation paths | [tests/](../tests/) |
| [ ] | Add router coverage for receipt printer, recharge failure | [router.py](../src/agent/router.py) |
| [ ] | API authentication (API key or JWT from .NET gateway) | **Critical** — **Blocked** until backend defines contract |
| [ ] | Bind `session_id` to authenticated `operator_id` | Prevent session hijack |
| [ ] | Rate limiting and `message` max length | FastAPI middleware |
| [x] | PCI: sanitize all ingress (`sanitize_user_text`) | server.py, app.py, routes.py, main.py |
| [x] | PCI: mask escalation summary/SMS; CVV guardrail; tests | security.py, graph.py, tests/test_security.py |
| [ ] | PCI: audit logs; remove full SMS body from mock log path | [notifications.py](../src/services/notifications.py) |
| [ ] | Generic 500 responses (no internal exception in `detail`) | [server.py](../src/api/server.py) |
| [ ] | Add `/ready` probe (OpenAI, Chroma, Setomatic reachable) | Keep `/health` as liveness only |
| [ ] | Escalation idempotency (skip re-dispatch if already sent) | [graph.py](../src/agent/graph.py) |
| [ ] | Prod env: fail startup if `USE_MOCK_REFUNDS=true` | [config.py](../src/config.py) |
| [ ] | Remove or gate legacy `main.py`, `/query`, `/notify/*` | Deploy `server.py` only |
| [ ] | CI: run `test_outage_workflow` + `test_security` on every PR | GitHub Actions / Azure Pipelines |
| [ ] | Dockerfile for agent API | infra vendor review |
| [ ] | Structured log shipping | Datadog / CloudWatch / Loki |
| [ ] | Strip localhost from prod CORS | Env-specific config |

**Exit criteria:** Per-intent escalation matches Intent Matrix; auth when .NET team delivers; CI green; no unauthenticated legacy routes.

---

## Phase 3 — Production infrastructure

**Goal:** Scalable deployment on Rackspace (preferred) with shared KB index and durable sessions.  
**Owner:** infra vendor (+ dev1 for ingest CLI)

| Status | Task | Notes |
|--------|------|-------|
| [ ] | Deploy agent API on Rackspace (containers) | Same cloud as SpyderWash FE/BE |
| [ ] | Pre-warm RAG/embeddings on startup; right-size memory | Mitigate cold start |
| [ ] | Rackspace Cloud Files → ingest job for Bible PDF | [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| [ ] | Migrate Chroma → Qdrant (or managed vector DB) | **Critical** for multi-replica |
| [ ] | Persistent checkpoint store (PostgreSQL / Redis) | Replace in-memory MemorySaver |
| [ ] | Environment matrix: dev / qa / uat / prod | URLs, secrets, feature flags |
| [ ] | Secrets in platform store (Mandrill, Twilio, OpenAI) | Never commit `.env` |
| [ ] | KB re-ingest pipeline (CLI or webhook) | Before admin UI |
| [ ] | Load testing on `/api/v1/agent/chat` | 10s SLA warning already in server |
| [ ] | Network policy: mock `:8001` not reachable from prod | Refunds hit live Setomatic only |
| [ ] | .NET Super Admin widget → prod agent API | Setomatic frontend team |
| [ ] | Circuit breakers / retries for external APIs | OpenAI, Setomatic |

**Exit criteria:** Two+ API replicas; shared vector DB; durable checkpoints; Bible ingest from Rackspace; .NET prod widget live; `/ready` green.

---

## Phase 4 — Voice (deferred)

**Goal:** Twilio voice channel for operators.  
**Owner:** infra vendor

| Status | Task | Notes |
|--------|------|-------|
| [ ] | Twilio Media Streams WebSocket endpoint | Separate from REST `/chat` |
| [ ] | STT → LangGraph → TTS pipeline | Reuse same graph |
| [ ] | Voice-specific latency and barge-in handling | Not required for web chat |

---

## Phase 5 — Platform (future)

**Owner:** infra vendor + product

| Status | Task | Notes |
|--------|------|-------|
| [ ] | SpyderWash KB Admin (Brandon reference UX) | [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| [ ] | Dashboard: chunk stats, feedback log, test assistant | |
| [ ] | Generate suggested KB update from low-rated feedback | Approve before apply |
| [ ] | Pending updates queue + chunk editor (`chunk_id`, keywords) | Structured schema ADR-015 |
| [ ] | Operator thumbs up/down → Feedback API | [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) Tier 2 |
| [ ] | Upload + auto re-index (replace email/manual loop) | Super Admin / Rackspace webhook |
| [ ] | Video strategy implementation (transcripts and/or link catalog) | [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| [ ] | Bible image pipeline (OCR / figure links) if product rejects text-only MVP | [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| [ ] | Bilingual prompts/responses if product confirms | [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) |
| [ ] | Escalation rule management UI | Vendor SOW |
| [ ] | Customer Agent (separate product) | Out of Operator Agent scope |
| [ ] | LangSmith / continuous eval on production traces | Quality monitoring |
| [ ] | Multi-tenant operator isolation | If SaaS expansion |
| [ ] | Structured Bible chunks (Brandon schema) or section-aware ingest | [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |

---

## Dependency graph

```
Phase 0 (demo) — dev1
    └── Phase 1 (QA) — dev1 + dev2
            └── Phase 2 (hardening) — dev1
                    └── Phase 3 (Rackspace prod infra) — infra vendor
                            ├── Phase 4 (voice)
                            └── Phase 5 (Bible sync, videos, admin KB)
```

**Production GA** requires Phase 0–3 complete, including all **Critical** gaps in the gap register.

---

## Quick reference commands

```bash
uv sync
uv run python -m unittest tests.test_outage_workflow tests.test_security -v
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
uv run uvicorn src.api.mock_server:mock_app --port 8001 --reload
```

See [RUNBOOK.md](RUNBOOK.md) for full local setup.

---

## Related documents

- [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) — Brandon mail, KB Admin prototype
- [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) — Setomatic POS API requirements
- [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) — vendor requirements traceability
- [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) — Bible, images, videos, Rackspace
- [PRD.md](PRD.md) — requirements and feature status matrix
- [INTENT_MATRIX.md](INTENT_MATRIX.md) — intent routing
- [TECH_STACK.md](TECH_STACK.md) — stack choices
- [TESTING.md](TESTING.md) — verification
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
