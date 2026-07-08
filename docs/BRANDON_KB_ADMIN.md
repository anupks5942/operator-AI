# Brandon KB Admin & Continuous Learning

Product direction from **Brandon Hinsen** ([Mail.pdf](../SendAnywhere_546287/Mail.pdf), April 2026) and his local **SpyderWash KB Admin** prototype (screenshots in mail). Maps to [INTENT_MATRIX.md](INTENT_MATRIX.md) (routing/escalation) vs **structured KB chunks** (retrieval).

**Status:** **Not implemented** in this repo — Phase 5 target. MVP uses generic Chroma splits in [rag_service.py](../src/services/rag_service.py).

---

## Brandon mail — key facts

| Topic | Detail |
|-------|--------|
| **Legacy starting content** | Portal Manual (103 pp PDF), Condensed Troubleshooting Guide (6 pp Word), Voiceover Troubleshooting Guide (7 pp Word) — in repo `KB/` today |
| **Future sole source** | **SpyderWash Bible** — consolidates all material; **~500 pages** estimated when complete (Brandon mail) |
| **File formats** | PDF and Word; moving to **PDF-only** for consistency |
| **Update cadence** | **Weekly** uploads initially → **ad hoc** once KB is established |
| **Interim process** | Email notification when batches uploaded to cloud → **manual re-index** of agent |
| **Ideal process** | **Administrative portal** — upload content and train/re-index without vendor email loop |
| **Intent Matrix** | Brandon reviewed and revised spreadsheet — captured in [INTENT_MATRIX.md](INTENT_MATRIX.md) (29 rows) |
| **Escalation verification** | Confirm SMS-to-tech vs email-Monday rules per matrix — Phase 2 in agent |

---

## KB Admin Dashboard (Brandon prototype)

Local app (`localhost:5174` in screenshots) — reference UX, not production code in this repo.

### Features observed

| Feature | Purpose | Repo today |
|---------|---------|------------|
| **Dashboard stats** | Chunk count, pending updates, feedback records | **No** |
| **Generate suggested KB update** | Low-rated feedback → AI proposes new/edited chunk; **pending until approved** | **No** |
| **Pending KB updates** | Review `add_new_chunk` proposals with JSON payload before apply | **No** |
| **KB chunk editor** | Select chunk by ID; edit structured fields directly | **No** |
| **Feedback log** | Operator thumbs up/down + timestamps; view conversation | **No** |
| **Test assistant** | Send test query (e.g. “How do I refund a transaction?”) against local RAG | **Partial** — Streamlit/`curl` only |

### Structured chunk schema (Brandon prototype)

Each KB unit is **not** a raw 500-character split — it carries retrieval metadata:

```json
{
  "chunk_id": "sw_connectivity_no_connection_extended",
  "section_id": "SW-TROUBLE-CONNECTIVITY",
  "title": "Extended Troubleshooting for No Connection Error",
  "intent": "Provide additional steps for persistent No Connection errors...",
  "content": "...",
  "keywords": ["no connection", "bluetooth hub power cycle", "re-pairing"],
  "common_queries": [
    "What to do if no connection error persists?",
    "How to power cycle Bluetooth Hub?"
  ]
}
```

**Target:** ingest/embed `content` + index `keywords` / `common_queries` for hybrid retrieval; keep `chunk_id` for admin edits and audit.

---

## Prototype chunk inventory (21 chunks)

From Brandon’s chunk editor dropdown — mapped to **Intent Matrix rows** and **router intents** where applicable.

| chunk_id | Title (short) | Intent Matrix # | Router / route (target) |
|----------|---------------|-----------------|-------------------------|
| `sw_power_no_display` | Card reader not powering on | Hub / hardware | `technical_support` → RAG |
| `sw_power_voltage_test` | Verify power supply voltage | Hub setup | RAG |
| `sw_connectivity_profile_default` | Profile = Default error | Hub setup | RAG |
| `sw_connectivity_hub_pairing` | Pair control board to hub | 17 Reader Pairing | RAG |
| `sw_connectivity_hub_placement` | Hub placement / signal | 21 Reader Distance | RAG |
| `sw_connectivity_network_error` | Network error on reader | Connectivity | RAG |
| `sw_connectivity_offline_status` | Offline status on reader | Connectivity | RAG |
| `sw_connectivity_no_connection` | No connection error | Hub / outage-adjacent | RAG; may overlap outage workflow |
| `sw_connectivity_no_connection_extended` | Advanced no connection | Same | RAG (feedback-generated in prototype) |
| `sw_connectivity_no_connection_detailed` | Detailed no connection | Same | RAG |
| `sw_config_price_missing` | Missing/incorrect vend price | 10 Machine Pricing | RAG; conditional Email Phase 2 |
| `sw_hardware_machine_not_starting` | Machine not start after payment | 26 Machines Not Starting | **outage workflow** |
| `sw_dashboard_001` | Dashboard overview | 8 Machine Management | RAG |
| `sw_loc_edit_001` | Edit machine configuration | 8, 12 | RAG |
| `sw_loc_edit_pulses` | Pulse configuration | Pricing / portal | RAG |
| `sw_loc_edit_price_adjustment` | Adjust machine price | 10 Machine Pricing | RAG |
| `sw_refund_001` | Refund transactions | 7 Customer Refunds | **tool_node** + RAG |
| `sw_reports_common` | Report generation | Reporting (no matrix row) | RAG only |
| `sw_spyderwatch_enable` | Enable SpyderWatch | Portal guidance | RAG |
| `sw_free_wash` | Free wash report | 20 Free Wash Program | RAG |
| `sw_loyalty_card_reload` | Reload loyalty card | 29 Recharge Failure | RAG + conditional Email Phase 2 |

**Two layers:**

1. **Intent Matrix** — *when* to route, escalate, or call APIs ([INTENT_MATRIX.md](INTENT_MATRIX.md)).
2. **KB chunks** — *what* text to retrieve ([rag_service.py](../src/services/rag_service.py) today ignores this schema).

---

## Human-in-the-loop learning loop (target)

```
Operator chat → feedback (thumbs down)
        │
        ▼
Feedback store (Tier 2 Feedback API in SETOMATIC_BACKEND_APIS.md)
        │
        ▼
Admin: Generate suggested KB update (LLM reads Q + answer + feedback)
        │
        ▼
Pending update queue (approve / reject)
        │
        ▼
Approved chunk → re-embed → shared vector index (Qdrant)
        │
        ▼
Operator Agent RAG uses updated chunk on next query
```

**MVP shortcut:** Brandon edits Bible source or chunk JSON manually → dev1 re-ingests `KB/` → delete `chroma_db/`.

---

## Upload & notification workflow

| Stage | Process |
|-------|---------|
| **Now (interim)** | Product uploads PDF batch to cloud → email dev1 → manual `KB/` drop + re-ingest |
| **Brandon mail** | Uploads to vendor cloud (mail references **Chetu Cloud**); email notification |
| **Planning** | **Rackspace** Cloud Files + ingest webhook — [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) |
| **Target (Phase 5)** | Super Admin / KB Admin portal → upload → auto re-index |

---

## Backend APIs needed (Phase 5)

From [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) Tier 2 (future platform), tied to this vision:

| API | KB Admin use |
|-----|----------------|
| Feedback API | Thumbs up/down from operator chat |
| Conversation Logging API | “View conversation” in feedback log |
| Manual Upload / KB Versioning API | Portal upload + replace Bible version |
| KB Search API (optional) | Test assistant / audit retrieval |
| Escalation Summary API | Link feedback to escalation incidents |

Agent-side **Generate / approve pending update** can live in KB Admin BFF or dev1 service — not specified in Setomatic POS API doc today.

---

## Implementation phases

| Phase | Deliverable |
|-------|-------------|
| **Now** | Generic RAG; manual Bible ingest; Intent Matrix routing gaps Phase 2 |
| **1** | Bible (~500 pp) ingest test; section-aware or Brandon chunk import spike |
| **2** | Operator feedback capture on chat widget → store (API or agent log) |
| **3** | Shared Qdrant; ingest webhook on upload |
| **5** | KB Admin UI (dashboard, chunk editor, pending updates, test assistant) |

See [ROADMAP.md](ROADMAP.md) Phase 5.

---

## Related documents

- [INTENT_MATRIX.md](INTENT_MATRIX.md) — 29-row escalation/routing matrix
- [KB_AND_PLATFORM.md](KB_AND_PLATFORM.md) — Bible size, images, Rackspace
- [SETOMATIC_BACKEND_APIS.md](SETOMATIC_BACKEND_APIS.md) — Feedback & KB APIs
- [PRD.md](PRD.md) — Brandon client rules
- [DECISIONS.md](DECISIONS.md) — ADR-013, ADR-015
