# Setomatic Operator AI — Documentation

Self-contained documentation for continuing development without AI tooling. **Start here.**

Product requirements and a [documentation map by role](PRD.md#documentation-map) live in [PRD.md](PRD.md).

**Team labels:** **dev1** = backend / agent repo. **dev2** = React QA UI. **infra vendor** = deployment, Rackspace, vector DB (Phase 3+).

---

## Quick links

| Document | Purpose |
|----------|---------|
| [CODEBASE.md](CODEBASE.md) | **Repo file map** — what every file does |
| [PRD.md](PRD.md) | Product requirements, client rules, feature status |
| [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) | Vendor **Requirement understanding** doc → repo status |
| [ROADMAP.md](ROADMAP.md) | Phased backlog, team ownership, blockers |
| [TECH_STACK.md](TECH_STACK.md) | Current MVP stack vs target production |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System diagram, graph nodes, data flow |
| [API.md](API.md) | Production REST contract for React/.NET |
| [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) | Final Setomatic POS API scope: 7 APIs (4 core + 3 future platform) |
| [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) | Gregg TC1/TC2 outage workflow |
| [INTENT_MATRIX.md](INTENT_MATRIX.md) | Brandon matrix (29 rows) → router intents |
| [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) | Brandon mail — KB Admin prototype, chunk map, feedback loop |
| [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) | SpyderWash Bible, images, videos, Rackspace |
| [TESTING.md](TESTING.md) | Automated and manual test procedures |
| [RUNBOOK.md](RUNBOOK.md) | Local dev, demo prep, common failures |
| [ENVIRONMENT.md](ENVIRONMENT.md) | All environment variables |
| [DECISIONS.md](DECISIONS.md) | Architecture decision records (ADRs) |
| [ONBOARDING.md](ONBOARDING.md) | Guided tour for new developers |

Root [README.md](../README.md) — install and run commands. Copy [`.env.example`](../.env.example) → `.env`.

---

## Reading paths

### New backend developer

1. [CODEBASE.md](CODEBASE.md) — file map
2. [ONBOARDING.md](ONBOARDING.md) — guided tour
3. [ARCHITECTURE.md](ARCHITECTURE.md) — LangGraph design
4. [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) — highest-risk workflow
5. [TESTING.md](TESTING.md) — run regression tests before changing router/graph

### Frontend integrator (React QA / .NET prod)

1. [API.md](API.md) — `POST /api/v1/agent/chat`
2. [ENVIRONMENT.md](ENVIRONMENT.md) — CORS and URLs
3. [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) — multi-turn UX expectations
4. Swagger: `http://localhost:8000/docs` (with agent server running)

### Demo / client call prep

1. [RUNBOOK.md](RUNBOOK.md) — processes, escalation recipients
2. [TESTING.md](TESTING.md) — TC1/TC2 scripts
3. [PRD.md](PRD.md) — acceptance criteria

### Planning next sprint

1. [PRD.md](PRD.md) — implemented vs planned
2. [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) — vendor doc vs repo gaps
3. [ROADMAP.md](ROADMAP.md) — phased backlog with owners
4. [DECISIONS.md](DECISIONS.md) — locked choices

---

## Team and blockers (June 2026)

| Topic | Detail |
|-------|--------|
| **Phase 0–2 owner** | **dev1** (backend / agent repo) |
| **Phase 3+ infra** | **infra vendor** (Rackspace deploy, vector DB) |
| **QA UI** | **dev2** — React for QA/UAT only |
| **Prod UI** | .NET Super Admin portal (Setomatic frontend team) |
| **Refund APIs** | Not ready on beta — use mock `:8001` |
| **Auth contract** | TBD — backend web chat not started |
| **`operator_id` in tools** | Hardcoded `4` — Phase 1 fix |
| **SpyderWash Bible** | ~500 pages (Brandon mail); manual RAG ingest — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md), [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| **KB Admin / feedback loop** | Brandon prototype — Phase 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| **Operator videos** | Not in RAG; strategy TBD (transcripts vs links) — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| **Production hosting** | Rackspace preferred (alongside SpyderWash FE/BE) — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |

See [ROADMAP.md](ROADMAP.md) for full blocker table.

---

## Documentation maintenance rules

1. **Code + tests are truth** — when behavior changes, update docs in the same PR.
2. **Verify claims** — grep the codebase before documenting endpoints, env vars, or intent names.
3. **Run regression tests** before marking roadmap items complete:
   ```bash
   uv run python -m unittest tests.test_outage_workflow -v
   ```
4. **Do not document Groq** as required — RAG uses OpenAI ([DECISIONS.md](DECISIONS.md) ADR-009).
5. **Do not document SQLite checkpoints** — MemorySaver is in-process only.

---

## External client sources (not in repo)

- **Brandon KB mail** — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) (`SendAnywhere_546287/Mail.pdf`)
- **Requirement understanding** (vendor SOW) — [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) (`SendAnywhere_546287/Requrement understading.docx`)
- **API Requirements** (Setomatic backend) — [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) — final scope: 7 APIs (4 core + 3 future)
- Intent Matrix (Brandon, 29 rows) — [INTENT_MATRIX.md](INTENT_MATRIX.md)
- Chat 1 / Chat 2 PDFs — stakeholder notes
- Setomatic Summary / DDD docs — legacy context

When client docs and code disagree, update the PRD status matrix after fixing code or documenting an intentional gap.

---

## Status labels

| Label | Meaning |
|-------|---------|
| **Implemented** | Shipped in this repo, usable today |
| **Partial** | Core path works; gaps documented |
| **Planned** | On roadmap, not started |
| **Deferred** | Explicitly out of current scope |
