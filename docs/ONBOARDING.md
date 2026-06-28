# Setomatic/SpyderWash Operator AI — Onboarding Guide

Orient new developers to the codebase. Product scope and roadmap: [docs/README.md](README.md).

---

## Project overview

Operator AI is a LangGraph technical support agent for laundry operators:

- RAG over legacy manuals (ChromaDB)
- Live loyalty and transaction tools (Setomatic beta API)
- Refund tools (mock `:8001` until beta APIs ready)
- Global system status (web scrape)
- Gregg's troubleshoot-first escalation (email + SMS)
- Guardrails (no live hardware status, out-of-domain refusal)

| Item | Value |
|------|-------|
| Language | Python 3.10+ |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Frameworks | FastAPI, Streamlit, LangGraph, LangChain, ChromaDB, OpenAI |
| Quick start | [README.md](../README.md), [RUNBOOK.md](RUNBOOK.md) |
| File map | [CODEBASE.md](CODEBASE.md) |

---

## UI channels

| UI | Environment | Integration |
|----|-------------|-------------|
| Streamlit | Local dev only | In-process graph — [app.py](../app.py) |
| React (dev2) | QA / UAT | HTTP → `:8000/api/v1/agent/chat` |
| .NET Super Admin | Production (planned) | Same API |

---

## Architecture layers

### Interfaces and APIs

| File | Role |
|------|------|
| [app.py](../app.py) | Streamlit demo — in-process graph streaming |
| [src/api/server.py](../src/api/server.py) | **Production** REST API |
| [src/api/mock_server.py](../src/api/mock_server.py) | Mock **refund** endpoints only (`:8001`) |
| [main.py](../main.py) | Legacy `/query` + console harness — avoid |
| [src/api/routes.py](../src/api/routes.py) | Legacy router — deprecated |

Contract: [API.md](API.md)

### Agent orchestration

| File | Role |
|------|------|
| [src/agent/graph.py](../src/agent/graph.py) | LangGraph state machine, outage workflow |
| [src/agent/router.py](../src/agent/router.py) | Semantic router — **15 intents** |
| [src/agent/nodes.py](../src/agent/nodes.py) | RAG, guardrail, out-of-domain |
| [src/agent/tools.py](../src/agent/tools.py) | Setomatic APIs + status scrape |
| [src/agent/state.py](../src/agent/state.py) | Typed agent state |

Outage detail: [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md)

### Services

| File | Role |
|------|------|
| [src/services/rag_service.py](../src/services/rag_service.py) | KB ingest (PDF/DOCX), Chroma, RAG |
| [src/services/notifications.py](../src/services/notifications.py) | Mandrill + Twilio; mock when `USE_LIVE_NOTIFICATIONS=false` |
| [src/config.py](../src/config.py) | Environment configuration |

### Knowledge base

| Path | Notes |
|------|-------|
| [KB/](../KB/) | Source manuals — **only `.pdf` and `.docx` are ingested** (legacy; interim until SpyderWash Bible ships) |
| `chroma_db/` | Generated vector store (delete to force re-ingest) |

**Product direction:** “The Bible of SpyderWash” (~500 pages, Brandon mail) replaces legacy multi-manual `KB/`. Structured chunks + KB Admin feedback loop — Phase 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md). Operator videos are separate; not ingested today. Production target: Rackspace + ingest job → shared vector DB — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md).

`.txt` files in `KB/` are **not** loaded by [rag_service.py](../src/services/rag_service.py). Convert to PDF/DOCX or extend the loader.

---

## Key concepts

### LangGraph control plane

[graph.py](../src/agent/graph.py) wires router → RAG, tools, guardrails, escalation, refusal. **Read this before changing behavior.**

### Outage workflow (Gregg)

```
blast_radius_check → troubleshoot_first → confirm → escalate OR resolve
```

Not a single-shot RAG answer. See [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md).

### Semantic routing

[router.py](../src/agent/router.py) classifies 15 intents and extracts entities (`blast_radius`, `card_number`, `troubleshooting_failed`, etc.).

Full business mapping: [INTENT_MATRIX.md](INTENT_MATRIX.md) (29 Brandon rows).

### Tools

[tools.py](../src/agent/tools.py):

- Loyalty + transactions → **live** Setomatic API (hardcoded `OperatorId=4` — Phase 1 fix)
- Refunds → mock `:8001` or live per `USE_MOCK_REFUNDS`
- Sequential refund: history → eligibility → execute

### Session memory

`MemorySaver` keys on `session_id` (API) or Streamlit UUID. **Not durable** — lost on restart. Same ID required across turns.

### Notifications

Escalation sends email + SMS when `USE_LIVE_NOTIFICATIONS=true`. Per-intent routing is Phase 2. Config: [ENVIRONMENT.md](ENVIRONMENT.md).

### PCI masking

[sanitize_user_text](../src/utils/security.py) on ingress (API, Streamlit, legacy routes). [sanitize_outbound_text](../src/utils/security.py) on escalation email/SMS. CVV/track data → `pci_guardrail_node` (no LLM).

---

## Guided tour

1. [CODEBASE.md](CODEBASE.md) + [README.md](../README.md) + [PRD.md](PRD.md)
2. Entry points — [server.py](../src/api/server.py), [app.py](../app.py)
3. LangGraph — [graph.py](../src/agent/graph.py), [router.py](../src/agent/router.py), [state.py](../src/agent/state.py)
4. Escalation — [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md), [notifications.py](../src/services/notifications.py)
5. Tools — [tools.py](../src/agent/tools.py), [mock_server.py](../src/api/mock_server.py)
6. RAG — [rag_service.py](../src/services/rag_service.py), [KB/](../KB/), [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md)
7. Tests — [tests/test_outage_workflow.py](../tests/test_outage_workflow.py)

---

## Complexity hotspots

| File | Why |
|------|-----|
| [tools.py](../src/agent/tools.py) | Live/mock APIs, refund ordering, status scrape, hardcoded operator ID |
| [graph.py](../src/agent/graph.py) | Routing table, outage workflow, ReAct tool loop |
| [router.py](../src/agent/router.py) | Long system prompt, continuation rules |
| [server.py](../src/api/server.py) | Production API, telemetry, CORS |
| [rag_service.py](../src/services/rag_service.py) | Ingestion, metadata, retriever |

---

## Suggested first tasks

1. Run locally — [RUNBOOK.md](RUNBOOK.md)
2. `uv run python -m unittest tests.test_outage_workflow -v`
3. One RAG query + one outage query in Streamlit
4. Trace an intent from [router.py](../src/agent/router.py) → [graph.py](../src/agent/graph.py)
5. Read [INTENT_MATRIX.md](INTENT_MATRIX.md) before changing escalation

---

## Full documentation set

[docs/README.md](README.md) — index of all docs, reading paths, maintenance rules.
