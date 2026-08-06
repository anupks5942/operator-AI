"""
Vectorless RAG Pipeline — structured retrieval without embeddings.

Retrieval flow:
1. Router intent + device_type → SQLite lookup
2. Keyword fallback on search_terms
3. Recursive co-retrieval (BFS over SQLite rules)
4. Ordered context: primary first, companions in BFS order
"""
import time
import logging
from langchain_core.documents import Document
from src.models.article_schema import CanonicalArticle
from src.services.kb_database import (
    search_by_intent_and_device,
    search_by_keywords,
    log_retrieval,
)
from src.services.co_retrieval import expand_co_retrieval
from src.services.article_context import build_ordered_context
from src.services.page_index import route as page_index_route, get_leaf_for_article
from src.config import CO_RETRIEVAL_MAX_DEPTH

logger = logging.getLogger(__name__)


def _extract_keywords(query: str) -> list[str]:
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "it", "its", "this", "that", "these", "those", "my", "your",
        "i", "me", "we", "they", "he", "she", "him", "her", "us",
        "and", "or", "but", "not", "no", "so", "if", "then", "when",
        "what", "which", "who", "how", "where", "why", "all", "each",
        "every", "any", "some", "just", "very", "also", "there",
    }
    words = query.lower().split()
    return [w.strip(".,!?;:'\"()") for w in words if w.strip(".,!?;:'\"()") not in stop_words and len(w) > 2]


def _article_to_primary_document(article: CanonicalArticle) -> Document:
    """Minimal Document shell for build_ordered_context primary path."""
    return Document(
        page_content=article.raw_body or article.direct_answer,
        metadata={
            "article_id": article.article_id,
            "category": article.category,
            "product": article.product,
            "device_type": article.device_type,
            "intent": article.intent,
            "doc_type": "kb_article",
            "retrieval_method": "vectorless",
        },
    )


def vectorless_retrieve(
    query: str,
    intent: str = "",
    device_type: str = "",
    category: str = "",
    product: str = "",
    top_k: int = 6,
    max_co_depth: int | None = None,
) -> tuple[list[Document], dict]:
    """
    Vectorless retrieval: PageIndex pre-filter + structured lookup + keyword matching + recursive co-retrieval.

    Returns:
        (ordered_documents, co_retrieval_meta)
    """
    start_time = time.time()
    depth = max_co_depth if max_co_depth is not None else CO_RETRIEVAL_MAX_DEPTH
    retrieved_articles: list[CanonicalArticle] = []

    # PageIndex pre-filter: narrow candidate set by hierarchy
    page_index_candidates = page_index_route(
        query, hints={"category": category, "product": product, "device_type": device_type}
    )
    if page_index_candidates:
        from src.services.kb_database import get_article
        for aid in page_index_candidates[:top_k]:
            art = get_article(aid)
            if art:
                retrieved_articles.append(art)

    if not retrieved_articles and intent:
        retrieved_articles.extend(search_by_intent_and_device(intent, device_type, limit=top_k))

    if not retrieved_articles and intent:
        retrieved_articles.extend(search_by_intent_and_device(intent, "", limit=top_k))

    keywords = _extract_keywords(query)
    if not retrieved_articles and keywords:
        retrieved_articles.extend(search_by_keywords(keywords, device_type, limit=top_k))

    if not retrieved_articles and keywords:
        retrieved_articles.extend(search_by_keywords(keywords, "", limit=top_k))

    # Dedupe while preserving order
    seen: set[str] = set()
    unique_articles: list[CanonicalArticle] = []
    for a in retrieved_articles:
        if a.article_id not in seen:
            seen.add(a.article_id)
            unique_articles.append(a)
    primary_articles = unique_articles[:top_k]

    seed_ids = [a.article_id for a in primary_articles]
    co_result = expand_co_retrieval(seed_ids, max_depth=depth, exclude_ids=set(seed_ids))

    primary_docs = [_article_to_primary_document(a) for a in primary_articles]
    final_docs = build_ordered_context(
        primary_docs=primary_docs,
        companion_ids=co_result.companion_ids,
        retrieval_method="vectorless",
    )

    latency_ms = (time.time() - start_time) * 1000
    article_ids = [d.metadata.get("article_id", "") for d in final_docs if d.metadata.get("article_id")]

    # Compute page_index_leaf for traceability
    page_index_leaf = ""
    if article_ids:
        page_index_leaf = get_leaf_for_article(article_ids[0])

    # Rejected = page_index candidates that weren't selected
    rejected_ids = [aid for aid in page_index_candidates if aid not in set(article_ids)]

    log_retrieval(
        query=query,
        method="vectorless",
        intent=intent,
        device_type=device_type,
        articles_returned=article_ids,
        scores=[],
        latency_ms=latency_ms,
        co_retrieval_applied=len(co_result.companion_ids) > 0,
        page_index_leaf=page_index_leaf,
        rejected_ids=rejected_ids,
    )

    co_meta = {
        "method": "vectorless",
        "co_retrieval_applied": len(co_result.companion_ids) > 0,
        "companion_ids": co_result.companion_ids,
        "unresolved_ids": co_result.unresolved_ids,
        "cycles_skipped": len(co_result.cycles_skipped),
        "depth_by_id": co_result.depth_by_id,
        "latency_ms": latency_ms,
        "page_index_leaf": page_index_leaf,
        "rejected_ids": rejected_ids,
    }

    logger.info(
        "[VECTORLESS_RAG] %d primary + %d companions in %.1fms | intent=%s device=%s",
        len(primary_articles),
        len(co_result.companion_ids),
        latency_ms,
        intent,
        device_type,
    )

    return final_docs, co_meta
