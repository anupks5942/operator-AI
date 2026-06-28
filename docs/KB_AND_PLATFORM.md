# Knowledge Base & Platform Strategy

How the Operator Agent uses the SpyderWash knowledge base, operator videos, and Rackspace-hosted assets — current state vs production target.

**Last updated:** July 2026

---

## SpyderWash Bible (single KB document)

**Source:** Product owner is compiling **“The Bible of SpyderWash”** — intended as the **only** KB document for this Operator Agent. Brandon (April 2026 mail) estimates **~500 pages** when complete; consolidates Portal Manual (103 pp), troubleshooting guides, and new content.

| Aspect | Status |
|--------|--------|
| Single source of truth | **Recommended** — reduces conflicting retrieval vs multiple legacy manuals |
| Size (~500 pages) | **Feasible for RAG** — expect ~1–2k chunks at 500-char splits, or fewer with structured chunks — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Legacy interim content | Portal Manual 103 pp + 6 pp + 7 pp Word guides — repo `KB/` today |
| File formats | PDF + DOCX ingest; product moving to **PDF-only** uploads |
| Update cadence | Weekly initially → ad hoc; email notify → manual re-index until portal exists |
| Ingest today | **Manual** — drop PDF/DOCX into `KB/`, delete `chroma_db/`, restart ([RUNBOOK.md](RUNBOOK.md)) |
| Auto-sync when Bible updates | **Not implemented** |
| Structured chunks (Brandon schema) | **Not implemented** — generic character splits only — ADR-015 |
| Version tracking (“which Bible version?”) | **Not implemented** |

**MVP verdict:** Demo and UAT with a manually loaded Bible — **yes**. Production with automatic updates — **no** until ingest pipeline and portal upload exist.

---

## Bible embedded images

The Bible will include **diagrams and screenshots**, not just text. Current ingest is **text-only** (`PyPDFLoader` / `Docx2txtLoader`) — embedded images are not processed unless captioned in the extracted text.

| Capability | Status |
|------------|--------|
| Extract text from Bible PDF/DOCX | **Implemented** |
| Process embedded images / diagrams | **Not implemented** |
| OCR or vision caption at ingest | **Not implemented** |
| Return figure links in chat | **Not implemented** |
| Multimodal RAG at query time | **Deferred** |

### Image strategy options (decision required)

| Option | Description | Effort | MVP fit |
|--------|-------------|--------|---------|
| **A — Text-first (recommended for MVP)** | Product adds text captions/steps beside every diagram in the Bible source | Low | Best short-term — no code change |
| **B — OCR / caption at ingest** | Extract figures from PDF; OCR or GPT-4o vision → text chunks in Chroma | Medium | When QA proves text-only gaps |
| **C — Figure links** | Export figures to Rackspace; chunk metadata includes `figure_url` | Low–medium | Operators open diagram manually |
| **D — Multimodal RAG** | Image store + vision model at query time | High | Post-GA unless product insists |

**Current code:** Same as videos — [rag_service.py](../src/services/rag_service.py) has no image pipeline.

---

## Operator videos

Product owner also has **many operator guidance videos**. Storing files on cloud storage does **not** automatically make them searchable by the agent.

| Capability | Status |
|------------|--------|
| Play / host videos | **Out of agent scope** — portal or CDN serves files to operators |
| Ingest video into RAG | **Not implemented** — no transcription pipeline |
| Return video links in chat | **Not implemented** — possible future enhancement |
| Multimodal “watch video” in agent | **Deferred** |

### Video strategy options (decision required)

| Option | Description | Effort | Quality |
|--------|-------------|--------|---------|
| **A — Transcripts in RAG** | Transcribe videos (e.g. Whisper) → ingest text like Bible sections | Medium–high | Best AI answers from video content |
| **B — Link-only** | RAG from Bible; agent appends “Watch: [URL]” when relevant | Low | Operators still watch video manually |
| **C — Deferred** | Bible text only for v1; videos in portal only | None now | Videos not in AI context |

**Current code:** [rag_service.py](../src/services/rag_service.py) loads **PDF/DOCX text only**. No video or audio processing.

---

## Rackspace hosting (recommended alignment)

**Recommendation (accepted in planning):** Host the Bible PDF and operator video files on **Rackspace cloud** alongside SpyderWash frontend/backend deployments — shared network and operations.

**Important:** Files on Rackspace object storage alone are **not** sufficient. The agent needs:

```
Rackspace Cloud Files (Bible PDF + videos [+ transcripts])
        │
        ▼
Ingest job (on upload or schedule)
        │
        ▼
Shared vector index (Qdrant or equivalent — Phase 3)
        │
        ▼
Agent API container(s) on Rackspace
        │
        ▼
.NET / React chat → POST /api/v1/agent/chat
```

| Layer | Rackspace-ready today? |
|-------|------------------------|
| Object storage for Bible + videos | **Planned** — not wired to agent |
| Agent reads from object storage | **No** — reads local `KB/` + `./chroma_db` |
| Agent API deployed on Rackspace | **TBD** — no container/deploy manifest in repo |
| Multi-instance API + shared vector DB | **No** — local Chroma + in-memory MemorySaver |

Hosting target in [ROADMAP.md](ROADMAP.md) Phase 3 includes **Rackspace** as primary option (SpyderWash already there); Azure remains fallback if required.

---

## Production readiness (Bible + videos + Rackspace)

| Requirement | Ready? | Phase |
|-------------|--------|-------|
| Text RAG from Bible (manual ingest) | **Partial** | Now — test at ~500 pp when delivered |
| Brandon KB Admin (feedback, chunk editor, pending updates) | **No** | 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Bible embedded images / diagrams | **No** | 1–2 — strategy pending |
| Bible as only KB source (product direction) | **Aligned** — replace legacy `KB/` files when Bible ships | dev1 |
| Auto re-index when Bible updates on Rackspace | **No** | 3–5 |
| Super Admin KB upload → agent re-index | **No** — backend team building upload | 5 |
| Video content in AI answers | **No** — strategy TBD | 4–5 |
| Rackspace object storage → ingest pipeline | **No** | 3 |
| Shared vector DB (multi-replica) | **No** | 3 |
| Durable chat sessions | **No** | 3 |
| Outage workflow + escalation + PCI | **Yes (MVP)** | Done |

---

## Roadmap tasks (KB & platform)

| Status | Task | Owner |
|--------|------|-------|
| [ ] | Receive Bible PDF when ready (~500 pp); manual ingest; RAG quality test | dev1 |
| [ ] | Align ingest with Brandon chunk schema or section-aware splits | dev1 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| [ ] | Decide Bible **image** strategy (captions vs OCR vs figure links vs multimodal) | Product + dev1 |
| [ ] | Decide video strategy (transcripts vs links vs defer) | Product + dev1 |
| [ ] | Section-aware chunking for Bible headings | dev1 |
| [ ] | KB re-ingest CLI reading from Rackspace Cloud Files | dev1 + infra vendor |
| [ ] | Migrate Chroma → Qdrant on Rackspace | infra vendor (Phase 3) |
| [ ] | Super Admin upload triggers re-index webhook | backend team + dev1 |
| [ ] | Optional: video transcript ingest pipeline | dev1 (Phase 5) |

---

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — RAG path and system diagram
- [TECH_STACK.md](TECH_STACK.md) — Chroma vs Qdrant
- [DECISIONS.md](DECISIONS.md) — ADR-003, ADR-012, ADR-013, ADR-015
- [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) — Brandon mail, KB Admin prototype, chunk map
- [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) — vendor doc traceability
- [ROADMAP.md](ROADMAP.md) — phased delivery
- [PRD.md](PRD.md) — product requirements
