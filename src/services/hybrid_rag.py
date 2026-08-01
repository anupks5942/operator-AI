"""
Hybrid RAG Pipeline — combines vector similarity with structured filtering.

Retrieval flow:
1. Qdrant vector similarity search (k=12, MMR)
2. Filter results by device_type metadata
3. Apply source priority (v2.2 articles > Bible chunks)
4. FlashRank reranking to top results
5. Recursive co-retrieval from SQLite rules (BFS, max depth)
6. Ordered context: primary procedures first, then companion chain
"""
import time
import logging
from langchain_core.documents import Document
from src.services.kb_database import log_retrieval
from src.services.co_retrieval import expand_co_retrieval
from src.services.article_context import build_ordered_context
from src.config import CO_RETRIEVAL_MAX_DEPTH

logger = logging.getLogger(__name__)


def hybrid_retrieve(
    query: str,
    vectorstore,
    intent: str = "",
    device_type: str = "",
    top_k: int = 6,
    rerank_fn=None,
    max_co_depth: int | None = None,
) -> tuple[list[Document], dict]:
    """
    Hybrid retrieval: vector search + metadata filter + priority + recursive co-retrieval.

    Returns:
        (ordered_documents, co_retrieval_meta)
    """
    start_time = time.time()
    co_meta: dict = {"method": "hybrid", "co_retrieval_applied": False}

    if not vectorstore:
        return [], co_meta

    depth = max_co_depth if max_co_depth is not None else CO_RETRIEVAL_MAX_DEPTH

    search_kwargs = {"k": 12, "fetch_k": 40, "lambda_mult": 0.5}
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs=search_kwargs,
    )
    raw_docs = retriever.invoke(query)

    if device_type:
        filtered_docs = []
        for doc in raw_docs:
            doc_device = doc.metadata.get("device_type", "") or doc.metadata.get("product", "")
            if not doc_device:
                filtered_docs.append(doc)
                continue
            doc_device_lower = doc_device.lower()
            device_lower = device_type.lower()
            if device_lower in doc_device_lower or doc_device_lower in device_lower:
                filtered_docs.append(doc)
            elif doc.metadata.get("device_type", "") == "General":
                filtered_docs.append(doc)
        if filtered_docs:
            raw_docs = filtered_docs

    _PRIORITY_ORDER = {
        "kb_article": 0,
        "bible_operator": 1,
        "bible_supplement": 2,
        "general": 3,
        "visual_reference": 4,
    }
    raw_docs.sort(key=lambda d: _PRIORITY_ORDER.get(d.metadata.get("doc_type", "general"), 3))

    if rerank_fn and raw_docs:
        primary_docs = rerank_fn(query, raw_docs, top_k=top_k)
    else:
        primary_docs = raw_docs[:top_k]

    seed_ids = [
        d.metadata.get("article_id", "")
        for d in primary_docs
        if d.metadata.get("article_id")
    ]
    co_result = expand_co_retrieval(seed_ids, max_depth=depth, exclude_ids=set(seed_ids))

    final_docs = build_ordered_context(
        primary_docs=primary_docs,
        companion_ids=co_result.companion_ids,
        retrieval_method="hybrid",
    )

    latency_ms = (time.time() - start_time) * 1000
    article_ids = [d.metadata.get("article_id", "") for d in final_docs if d.metadata.get("article_id")]

    log_retrieval(
        query=query,
        method="hybrid",
        intent=intent,
        device_type=device_type,
        articles_returned=article_ids,
        scores=[],
        latency_ms=latency_ms,
        co_retrieval_applied=len(co_result.companion_ids) > 0,
    )

    co_meta = {
        "method": "hybrid",
        "co_retrieval_applied": len(co_result.companion_ids) > 0,
        "companion_ids": co_result.companion_ids,
        "unresolved_ids": co_result.unresolved_ids,
        "cycles_skipped": len(co_result.cycles_skipped),
        "depth_by_id": co_result.depth_by_id,
        "latency_ms": latency_ms,
    }

    logger.info(
        "[HYBRID_RAG] %d primary + %d companions (depth≤%d) in %.1fms | device=%s unresolved=%s",
        len(primary_docs),
        len(co_result.companion_ids),
        depth,
        latency_ms,
        device_type,
        co_result.unresolved_ids,
    )

    return final_docs, co_meta
