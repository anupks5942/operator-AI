# Knowledge Base & Platform Strategy

How the Operator Agent uses the SpyderWash knowledge base, operator videos, and Rackspace-hosted assets — current state vs production target.

**Last updated:** July 24, 2026

---

## KB Source Documents (dual-doc strategy)

**Per Brandon (Jul 17, 2026):** The RAG corpus uses **two co-primary documents** until the Bible is complete:

1. **SpyderWash_AI_Support_Knowledge_Base (v2.2)** — the AI-optimized, article-structured version (171 articles with ARTICLE START/END boundaries, structured metadata, and explicit RAG ingestion rules). Created specifically for chatbot integration.
2. **Setomatic Bible** — raw source material (261 pages / 47.9 MB). Contains network/power troubleshooting content plus brand-specific wiring/installation instructions.

**v1.8 is superseded** — Brandon confirmed deletion. Only v2.2 and Bible are active.

**Future state:** Once the Bible is complete (pending: company/product overview, redesigned site/app content), v2.2 will be retired and the Bible will be the sole KB source. Brandon will confirm timing.

| Aspect | Status |
|--------|--------|
| v2.2 as primary AI source | **Active** — 171 structured articles, article-aware chunking (ADR-030) |
| Bible as supplementary source | **Active** — troubleshooting (1-14) + operator FAQ through Highest-Frequency Questions; brand wiring / PCI / Voiceover excluded |
| Bible size | **261 pages / 47.9 MB** (not ~500 pp as previously estimated) |
| v1.8 status | **Superseded** — confirmed for removal by Brandon (Jul 17, 2026) |
| Content ownership | **Brandon / Setomatic** — Chetu must **not** invent KB source content |
| Brandon maintaining v2.2 | **Yes** — confirmed to continue alongside Bible until Bible ships complete |
| Company/product overview | **Pending** — Brandon will add to Bible in a future update |
| Self-service KB training | **Critical priority** for Brandon's team (Phase 5 in roadmap, flagged as urgent) |

---

## RAG Ingestion Architecture (ADR-030)

```
v2.2 DOCX
   │
   ├── Section 0 (17.8K chars) → Injected into RAG system prompt (NOT chunked)
   │     Contains: AI Retrieval and Response Rules, security, RMA, financial accuracy
   │
   ├── 171 Articles → ONE atomic chunk per article
   │     Metadata: article_id, category, product, intent, search_terms, status
   │     Avg size: 1550 chars (max 2724, min 787)
   │     Co-retrieval rules parsed and enforced at query time
   │
   └── Post-article visual refs → Chunked with doc_type=visual_reference

Bible DOCX
   │
   ├── Sections 1-14 → doc_type=bible_supplement
   │     Covers: Network errors, power issues, connectivity, ISP coordination
   │
   ├── Operator Portal → Voiceover marker → doc_type=bible_operator
   │     Covers: Portal/POS/Kiosk/Hub FAQ, Installation FAQ (Relay vs Serial
   │     Control Board, Bluetooth ID, hubs), Highest-Frequency Questions
   │
   └── Brand wiring diagrams, Voiceover transcript, PCI notes, RMA SOP → EXCLUDED
```

### Retrieval pipeline

1. **MMR retrieval** — k=12, fetch_k=40, lambda=0.5
2. **FlashRank reranking** — `ms-marco-TinyBERT-L-2-v2`, top 6 after rerank (ADR-032)
3. **Co-retrieval** — 17 articles have mandatory companion articles (e.g., KB-POS-007 for all POS scale queries)
4. **LLM generation** — Section 0 rules in system prompt; context = reranked + companion docs
5. **Category metadata filter** — only for narrow intents; **not** for `technical_support` (ADR-033)
6. **Short follow-up expansion** — ≤6-word affirmatives/requests expand from prior AI / last `KB-…` article_id (ADR-036)
7. **Resolve prompt** — content markers (± intent); skip definitional / trailing-offer answers (ADR-034/035)

### Metadata fields indexed in Qdrant

| Field | Source | Example |
|-------|--------|---------|
| `article_id` | v2.2 ARTICLE ID | KB-READER-007 |
| `category` | v2.2 METADATA line | No Connection Error |
| `product` | v2.2 METADATA line | EMV Reader / Control Board / Bluetooth Hub |
| `intent` | v2.2 METADATA line | Offline |
| `search_terms` | v2.2 METADATA line | offline; reader; control board; hub |
| `status` | v2.2 STATUS line | current |
| `source_priority` | Computed | primary (v2.2) / secondary (Bible) |
| `doc_type` | Computed | kb_article / bible_supplement / bible_operator / visual_reference |
| `brand` | Computed | SpyderWash |
| `co_retrieval_ids` | v2.2 CO-RETRIEVAL RULE | KB-POS-007 |

---

## Bible embedded images

The Bible and v2.2 include **diagrams and screenshots**. v2.2's post-article section contains image descriptions with text captions. Current ingest is **text-only** — images are not rendered but their captions are chunked.

| Capability | Status |
|------------|--------|
| Extract text from Bible/v2.2 PDF/DOCX | **Implemented** |
| v2.2 image descriptions (text captions) | **Implemented** — chunked as visual_reference |
| Process embedded images / diagrams | **Not implemented** |
| OCR or vision caption at ingest | **Not implemented** |
| Multimodal RAG at query time | **Deferred** |

### Image strategy options (decision required)

| Option | Description | Effort | MVP fit |
|--------|-------------|--------|---------|
| **A — Text-first (recommended for MVP)** | Product adds text captions/steps beside every diagram in the Bible source | Low | Best short-term — no code change |
| **B — OCR / caption at ingest** | Extract figures from PDF; OCR or GPT-4o vision → text chunks in Qdrant | Medium | When QA proves text-only gaps |
| **C — Figure links** | Export figures to Rackspace; chunk metadata includes `figure_url` | Low–medium | Operators open diagram manually |
| **D — Multimodal RAG** | Image store + vision model at query time | High | Post-GA unless product insists |

---

## Operator videos (~24 YouTube guidance videos)

Product has operator guidance videos (about **24** YouTube videos referenced in planning). Storing files/links alone does **not** make them searchable unless mapped into the KB ingest path.

| Capability | Status |
|------------|--------|
| Play / host videos | **Out of agent scope** — YouTube / portal / CDN serves files to operators |
| Ingest full video transcripts into RAG | **Not preferred** — complex, high token/ops cost |
| Return video links in chat | **Planned** via doc-section mapping (Option B below) |
| Multimodal "watch video" in agent | **Deferred** |

### Video upload timeline (open with Brandon)

Chetu asked whether documentation for **all 24 videos** will be ready before UAT, or added **incrementally** (like other docs). This affects ingest-pipeline design. **Awaiting Brandon's reply.**

### Video strategy (proposed — Option B preferred)

| Option | Description | Effort | Decision |
|--------|-------------|--------|----------|
| **A — Transcript RAG** | Extract YouTube transcripts → embed/search → return video URL | Medium–high | **Not preferred** — complex; higher LLM token / ops cost |
| **B — Documentation mapping (recommended)** | Place the relevant video URL **in the Bible/docs** next to the matching section (e.g. hub setup steps + YouTube link). Ingest maps content → link during RAG | Low | **Preferred** — simpler, more accurate, cost-effective |
| **C — Defer** | Bible text only for v1; videos only on portal/YouTube | None now | Fallback until Bible sections include links |

**Implementation implication (Option B):** When Brandon adds/updates Bible sections, each relevant section should include the YouTube URL inline. RAG retrieves that chunk; the agent surfaces the link with the answer. No separate Whisper/transcript pipeline required for MVP.

---

## Rackspace hosting (recommended alignment)

**Recommendation (accepted in planning):** Host the Bible PDF and operator video files on **Rackspace cloud** alongside SpyderWash frontend/backend deployments — shared network and operations.

**Important:** Files on Rackspace object storage alone are **not** sufficient. The agent needs:

```
Rackspace Cloud Files (Bible PDF + v2.2 + videos)
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
| Object storage for Bible + v2.2 + videos | **Planned** — not wired to agent |
| Agent reads from object storage | **No** — reads local `KB/` + `./spyderwash_qdrant/` |
| Agent API deployed on Rackspace | **TBD** — no container/deploy manifest in repo |
| Multi-instance API + shared vector DB | **No** — local Qdrant + in-memory MemorySaver |

Hosting target in [ROADMAP.md](ROADMAP.md) Phase 3 includes **Rackspace** as primary option (SpyderWash already there); Azure remains fallback if required.

---

## Production readiness (KB + videos + Rackspace)

| Requirement | Ready? | Phase |
|-------------|--------|-------|
| Article-aware RAG from v2.2 (171 articles) | **Implemented** (ADR-030) | Done |
| Bible supplement + operator FAQ ingestion | **Implemented** (ADR-030) | Done |
| FlashRank reranking (`ms-marco-TinyBERT-L-2-v2`) | **Implemented** (ADR-032) | Done |
| Co-retrieval rules | **Implemented** | Done |
| Section 0 system prompt injection | **Implemented** | Done |
| Brandon KB Admin (feedback, chunk editor, pending updates) | **No** | 5 — [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) |
| Bible embedded images / diagrams | **No** | 1–2 — strategy pending |
| Auto re-index when Bible updates on Rackspace | **No** | 3–5 |
| Super Admin KB upload → agent re-index | **No** — backend team building upload | 5 |
| Video content in AI answers | **Partial plan** — Option B: URLs embedded in Bible sections | 4–5 (after Brandon confirms) |
| Rackspace object storage → ingest pipeline | **No** | 3 |
| Shared vector DB (multi-replica) | **No** | 3 |
| Durable chat sessions | **No** | 3 |
| Outage workflow + escalation + PCI | **Yes (MVP)** | Done |

---

## Roadmap tasks (KB & platform)

| Status | Task | Owner |
|--------|------|-------|
| [x] | Article-aware v2.2 ingestion (171 articles as atomic chunks with metadata) | dev1 — ADR-030 |
| [x] | Selective Bible ingestion (troubleshooting + operator FAQ; exclude wiring/PCI) | dev1 — ADR-030 |
| [x] | FlashRank reranking (`ms-marco-TinyBERT-L-2-v2`, top 6 from MMR 12) | dev1 — ADR-032 |
| [x] | Stop category-filtering `technical_support` (printer / Control Board RAG) | dev1 — ADR-033 |
| [x] | Resolve-prompt guards (definitional + trailing question) | dev1 — ADR-035 |
| [x] | Short follow-up RAG query expansion (KB article_id / prior topic) | dev1 — ADR-036 |
| [x] | Post-escalation sticky-state / blast-radius dedup / ticket-notes gate | dev1 — ADR-037 |
| [x] | Co-retrieval rules (17 articles with mandatory companions) | dev1 |
| [x] | Section 0 system prompt injection | dev1 |
| [x] | Prefer video **Option B** (URL in Bible section) over transcript RAG | Proposed to Brandon |
| [ ] | Decide Bible **image** strategy (captions vs OCR vs figure links vs multimodal) | Product + dev1 |
| [ ] | Confirm video upload timeline (all 24 before UAT vs incremental) | Brandon |
| [ ] | When Bible sections include YouTube URLs, verify RAG returns link + steps | dev1 |
| [ ] | KB re-ingest CLI reading from Rackspace Cloud Files | dev1 + infra vendor |
| [ ] | Deploy Qdrant on Rackspace (shared instance) | infra vendor (Phase 3) |
| [ ] | Super Admin upload triggers re-index webhook | backend team + dev1 |
| [ ] | Remove v1.8 from KB/_archive (confirmed superseded) | dev1 |
| [ ] | Optional: video transcript ingest pipeline | **Deferred** — not preferred vs Option B |

---

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — RAG path and system diagram
- [TECH_STACK.md](TECH_STACK.md) — Qdrant vector store
- [DECISIONS.md](DECISIONS.md) — ADR-003, ADR-012, ADR-013, ADR-015, ADR-030–037
- [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) — Brandon mail, KB Admin prototype, chunk map
- [REQUIREMENTS_MAP.md](REQUIREMENTS_MAP.md) — vendor doc traceability
- [ROADMAP.md](ROADMAP.md) — phased delivery
- [PRD.md](PRD.md) — product requirements
