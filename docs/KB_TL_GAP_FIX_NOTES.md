# KB TL Gap Fix Notes

## Summary of fixes (excluding images)

| Gap | Fix |
|-----|-----|
| Recursive case mapping | BFS co-retrieval engine (`max_depth=3`, cycle/dedupe, unresolved reporting) |
| Step continuation / ordering | PRIMARY PROCEDURE → CONTINUE WITH RELATED PROCEDURE context blocks + prompt rules |
| Live Hybrid wiring | `RAG_RETRIEVAL_METHOD=hybrid` default in live `RAGService` + intent/device from router |
| Benchmark evidence | Numbers included below from `tests/benchmark_results.json` |

## Qdrant vs SQLite roles

| Store | Role |
|-------|------|
| **Qdrant** | Semantic vector search (MMR + FlashRank) — finds related articles by meaning |
| **SQLite** | Structured articles, co-retrieval rules, search terms, device mappings, logs |
| **Hybrid (production default)** | Qdrant for recall + SQLite for recursive co-retrieval and structured step fields |

Vectorless path uses SQLite only (no embeddings). Hybrid intentionally uses both.

## Co-retrieval policy

- **Algorithm:** Breadth-first search over `co_retrieval_rules` table
- **Max depth:** 3 levels (configurable via `CO_RETRIEVAL_MAX_DEPTH`)
- **Multiple children:** All direct companions of a node are enqueued; duplicates removed via visited set
- **Cycle prevention:** Re-visiting an already-seen article ID skips the edge and logs `cycles_skipped`
- **Unresolved references:** Companion ID in rules but missing from SQLite → logged in `unresolved_ids`
- **Ordering:** Primary matched articles first; companions in BFS discovery order

## Step ordering policy

1. Context blocks labeled `PRIMARY PROCEDURE` for top-ranked articles
2. Companion blocks labeled `CONTINUE WITH RELATED PROCEDURE (after primary steps)`
3. LLM prompt instructs: complete primary steps in order, then continue companion steps
4. Article IDs never shown to operator; steps merged into one unified answer
5. Device-specific procedures must not be mixed across POS / Kiosk / Hub / Card Reader

## Benchmark results (50 test cases)

| Method | Accuracy | Co-retrieval | Wrong-device rate | Avg latency |
|--------|----------|--------------|-------------------|-------------|
| Vectorless | 72.0% (36/50) | 90.0% (9/10) | 4.0% | 73.4 ms |
| Vector (Qdrant) | 90.0% (45/50) | 100.0% (10/10) | 28.0% | 485.7 ms |
| Hybrid | 86.0% (43/50) | 90.0% (9/10) | 13.0% | 997.1 ms |

**Conclusion:** Hybrid selected as production default — best balance of accuracy and wrong-device prevention. Vectorless remains available for zero-embedding-cost scenarios.

## Configuration

```env
RAG_RETRIEVAL_METHOD=hybrid   # hybrid | vector | vectorless
CO_RETRIEVAL_MAX_DEPTH=3
```

## Files added/updated

- `src/services/co_retrieval.py` — recursive BFS engine
- `src/services/article_context.py` — ordered PRIMARY/CONTINUE context builder
- `src/services/hybrid_rag.py` — uses recursive co-retrieval + ordered context
- `src/services/vectorless_rag.py` — same recursive engine
- `src/services/rag_service.py` — Hybrid default live path
- `src/agent/nodes.py` — passes intent + device_type to RAG
- `src/config.py` — `RAG_RETRIEVAL_METHOD`, `CO_RETRIEVAL_MAX_DEPTH`
- `tests/test_co_retrieval.py` — unit tests for BFS/cycle/depth/unresolved
