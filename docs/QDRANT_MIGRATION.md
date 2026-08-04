# Qdrant Migration Documentation

## 1. Overview

The SpyderWash Operator AI migrated from ChromaDB to **Qdrant** (local on-disk mode) as the production vector store for RAG retrieval. ChromaDB has been fully removed from the codebase, dependencies, and runtime.

**Why Qdrant:**
- Native payload indexing for filtered search (device_type, category, intent)
- Superior performance on structured metadata queries
- On-disk mode eliminates external service dependency for local dev
- Built-in support for sparse vectors and hybrid search (RRF fusion)
- Better observability via collection info and payload schema inspection

## 2. Setup

### Local on-disk deployment (current production path)

No Docker or server required. Qdrant stores data at `./spyderwash_qdrant/` relative to project root.

```bash
# Install dependencies
uv sync

# Build the vector index from KB/ source documents
uv run python -m data_injection

# Verify
uv run python -c "from qdrant_client import QdrantClient; c=QdrantClient(path='./spyderwash_qdrant'); print(c.get_collection('spyderwash_docs'))"
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_PATH` | `./spyderwash_qdrant` | Local Qdrant storage directory |
| `QDRANT_COLLECTION` | `spyderwash_docs` | Collection name |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `RAG_RETRIEVAL_METHOD` | `hybrid` | Retrieval mode: `vector`, `vectorless`, `hybrid` |
| `CO_RETRIEVAL_MAX_DEPTH` | `3` | BFS depth for co-retrieval expansion |

## 3. Schema Mapping (Chroma → Qdrant)

| Chroma concept | Qdrant equivalent |
|----------------|-------------------|
| Collection `spyderwash_docs` | Collection `spyderwash_docs` |
| Document ID (string) | Point UUID |
| Document text | Payload field `page_content` |
| Metadata dict | Payload under `metadata.*` namespace |
| Cosine similarity | `Distance.COSINE` |
| 1536 dimensions | `VectorParams(size=1536)` |
| `where` filters | `Filter(must=[...])` via `to_qdrant_filter()` |

### Payload indexes (created during ingest)

| Field | Type | Purpose |
|-------|------|---------|
| `metadata.article_id` | KEYWORD | Exact-match article lookup |
| `metadata.category` | KEYWORD | Category-scoped retrieval |
| `metadata.intent` | KEYWORD | Intent-scoped retrieval |
| `metadata.device_type` | KEYWORD | Device-specific filtering |
| `metadata.product` | KEYWORD | Product filtering |
| `metadata.audience` | KEYWORD | Audience filtering |
| `metadata.status` | KEYWORD | Active/deprecated filtering |
| `metadata.source_priority` | INTEGER | Priority ordering |

## 4. Ingest Command

```bash
# Full reingest (default — deletes existing store first)
uv run python -m data_injection

# Options
uv run python -m data_injection --kb-dir KB --force
uv run python -m data_injection --no-force  # fails if collection exists
```

The ingest pipeline:
1. Parses all `.docx` files in `KB/` via `data_injection/kb_parser.py`
2. Extracts Section 0 → writes `spyderwash_section0.txt` cache
3. Creates Qdrant collection with vector config + 8 payload indexes
4. Embeds documents in batches of 32 via OpenAI API
5. Writes points to local Qdrant store

## 5. Retrieval Layer

Three modes configured via `RAG_RETRIEVAL_METHOD`:

| Mode | Path | Description |
|------|------|-------------|
| `vector` | Qdrant MMR → FlashRank rerank | Pure dense vector retrieval |
| `vectorless` | SQLite keyword + intent + device | No embeddings, structured only |
| `hybrid` (default) | Qdrant MMR + device filter + FlashRank + SQLite co-retrieval | Best accuracy (86% on 50 test cases) |

All modes use `expand_co_retrieval()` BFS for linked-case expansion.

## 6. Rollback Procedure

If catastrophic Qdrant failure requires rollback:

1. **Immediate:** Switch to vectorless mode (no Qdrant required):
   ```bash
   # In .env
   RAG_RETRIEVAL_METHOD=vectorless
   ```

2. **Data recovery:** Reingest from source KB docs:
   ```bash
   uv run python -m data_injection --force
   ```

3. **Historical note:** ChromaDB was removed from `pyproject.toml` and all imports. Re-adding Chroma would require restoring the dependency, rewriting retrieval calls, and is NOT recommended.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Collection 'spyderwash_docs' does not exist` | Qdrant not initialized | Run `uv run python -m data_injection` |
| `Collection is empty` | Ingest failed midway (e.g., API timeout) | Run `uv run python -m data_injection --force` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Corporate proxy SSL inspection | Set `SSL_CERT_FILE` env var to corporate CA bundle, or use VPN bypass |
| `openai.APITimeoutError` | Network/VPN blocking OpenAI | Fix network, then reingest |
| `Failed to open local Qdrant` | Corrupted store | Delete `spyderwash_qdrant/` and reingest |
| Slow first query | Cold start (loading collection into memory) | Expected — subsequent queries are fast |
| Empty search results | Payload filter mismatch | Check filter values via `/api/v1/kb/diagnostics` |

## 8. Environment Variable Reference

See [ENVIRONMENT.md](ENVIRONMENT.md) for the full list. Qdrant-specific:

```env
QDRANT_PATH=./spyderwash_qdrant
QDRANT_COLLECTION=spyderwash_docs
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
RAG_RETRIEVAL_METHOD=hybrid
CO_RETRIEVAL_MAX_DEPTH=3
```

## 9. Monitoring

The `/api/v1/kb/diagnostics` endpoint now returns a `monitoring_24h` block:

```json
{
  "monitoring_24h": {
    "total_queries_24h": 150,
    "empty_search_rate_24h": 2.5,
    "error_rate_24h": 0.0,
    "payload_filter_failure_rate_24h": 1.2,
    "avg_latency_ms_24h": 450.3
  }
}
```

Logged per-query in `retrieval_logs` table with `error_type`, `empty_result`, and `payload_filter_failed` columns.
