"""Sparse hybrid search — BM25 sparse vectors + dense vectors with RRF fusion.

Feature-flagged via RAG_SPARSE_HYBRID_ENABLED. When enabled, replaces
the default dense+SQLite hybrid path with Qdrant-native RRF fusion.

Requires: fastembed, qdrant-client >= 1.18
"""
from __future__ import annotations

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    Filter,
    Fusion,
    FusionQuery,
    Prefetch,
    QueryRequest,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

logger = logging.getLogger(__name__)

_BM25_MODEL_NAME = "Qdrant/bm25"


def create_sparse_hybrid_collection(
    client: QdrantClient,
    collection: str,
    dense_dims: int = 1536,
):
    """Create a collection with both dense and sparse vector configs."""
    if client.collection_exists(collection):
        client.delete_collection(collection)

    client.create_collection(
        collection_name=collection,
        vectors_config={
            "dense": VectorParams(size=dense_dims, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse_bm25": SparseVectorParams(),
        },
    )
    logger.info(
        "[SPARSE_HYBRID] Created collection '%s' with dense(%d) + sparse_bm25",
        collection, dense_dims,
    )


def get_bm25_embedder():
    """Lazy-load the fastembed BM25 sparse text embedding model."""
    from fastembed import SparseTextEmbedding
    return SparseTextEmbedding(model_name=_BM25_MODEL_NAME)


def compute_sparse_vector(embedder, text: str) -> SparseVector:
    """Compute BM25 sparse vector for a single text."""
    results = list(embedder.embed([text]))
    if not results:
        return SparseVector(indices=[], values=[])
    sparse = results[0]
    return SparseVector(
        indices=sparse.indices.tolist(),
        values=sparse.values.tolist(),
    )


def sparse_hybrid_search(
    client: QdrantClient,
    collection: str,
    query_dense: list[float],
    query_sparse: SparseVector,
    limit: int = 12,
    qdrant_filter: Optional[Filter] = None,
) -> list[dict]:
    """Execute RRF fusion search combining dense and sparse results.

    Uses Qdrant's native prefetch + fusion query for efficient hybrid retrieval.
    """
    prefetch_dense = Prefetch(
        query=query_dense,
        using="dense",
        limit=limit * 2,
        filter=qdrant_filter,
    )

    prefetch_sparse = Prefetch(
        query=query_sparse,
        using="sparse_bm25",
        limit=limit * 2,
        filter=qdrant_filter,
    )

    results = client.query_points(
        collection_name=collection,
        prefetch=[prefetch_dense, prefetch_sparse],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
    )

    docs = []
    for point in results.points:
        payload = point.payload or {}
        docs.append({
            "id": str(point.id),
            "score": point.score,
            "page_content": payload.get("page_content", ""),
            "metadata": payload.get("metadata", {}),
        })

    logger.info(
        "[SPARSE_HYBRID] RRF search returned %d results (dense+sparse prefetch=%d each)",
        len(docs), limit * 2,
    )
    return docs
