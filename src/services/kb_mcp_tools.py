"""
MCP Tool Endpoints for Knowledge Base retrieval.

Exposes the KB's structured retrieval capabilities as callable tools
for external agents (MCP protocol). Integrates with the existing
FastAPI server.

Tools exposed:
    - kb_search: Search articles by query text (uses hybrid retrieval)
    - kb_get_article: Retrieve a specific article by ID
    - kb_get_companions: Get co-retrieval articles for a given article
    - kb_diagnostics: Get retrieval system health and statistics
"""
import time
import logging
from typing import Optional
from pydantic import BaseModel, Field
from src.services.kb_database import (
    get_article,
    _get_connection,
)
from src.services.vectorless_rag import vectorless_retrieve
from src.services.co_retrieval import expand_co_retrieval
from src.config import CO_RETRIEVAL_MAX_DEPTH, RAG_RETRIEVAL_METHOD

logger = logging.getLogger(__name__)


# --- Pydantic schemas for tool inputs/outputs ---

class KBSearchInput(BaseModel):
    query: str = Field(..., description="The search query text")
    intent: str = Field(default="", description="Optional intent filter (e.g. 'No Connection Error')")
    device_type: str = Field(default="", description="Optional device filter (e.g. 'POS', 'Hub', 'Legacy Kiosk')")
    top_k: int = Field(default=6, description="Maximum number of articles to return")


class KBGetArticleInput(BaseModel):
    article_id: str = Field(..., description="The article ID to retrieve (e.g. 'KB-PORTAL-001')")


class KBGetCompanionsInput(BaseModel):
    article_id: str = Field(..., description="Article ID to get companions for")


class ArticleResponse(BaseModel):
    article_id: str
    category: str
    product: str
    device_type: str
    intent: str
    direct_answer: str
    recommended_steps: list[str]
    optional_steps: list[str]
    resolution_criteria: str
    escalation_condition: str
    evidence_to_collect: str


class SearchResult(BaseModel):
    articles: list[ArticleResponse]
    total_found: int
    method: str
    latency_ms: float


class DiagnosticsResponse(BaseModel):
    total_articles: int
    co_retrieval_rules: int
    search_terms_count: int
    device_types: list[str]
    categories: list[str]
    recent_queries: int
    co_retrieval_max_depth: int
    retrieval_method_default: str


class CompanionsResponse(BaseModel):
    article_id: str
    companions: list[ArticleResponse]
    ordered_companion_ids: list[str]
    unresolved_ids: list[str]
    cycles_skipped: int
    max_depth: int


# --- Tool implementations ---

def kb_search(input: KBSearchInput) -> SearchResult:
    """
    Search the knowledge base using vectorless retrieval.
    Returns matching articles with structured content.
    """
    start = time.time()

    docs, _co_meta = vectorless_retrieve(
        query=input.query,
        intent=input.intent,
        device_type=input.device_type,
        top_k=input.top_k,
    )

    articles = []
    for doc in docs:
        article_id = doc.metadata.get("article_id", "")
        if article_id:
            full_article = get_article(article_id)
            if full_article:
                articles.append(ArticleResponse(
                    article_id=full_article.article_id,
                    category=full_article.category,
                    product=full_article.product,
                    device_type=full_article.device_type,
                    intent=full_article.intent,
                    direct_answer=full_article.direct_answer,
                    recommended_steps=full_article.recommended_steps,
                    optional_steps=full_article.optional_steps,
                    resolution_criteria=full_article.resolution_criteria,
                    escalation_condition=full_article.escalation_condition,
                    evidence_to_collect=full_article.evidence_to_collect,
                ))

    latency = (time.time() - start) * 1000

    return SearchResult(
        articles=articles,
        total_found=len(articles),
        method="vectorless",
        latency_ms=round(latency, 1),
    )


def kb_get_article(input: KBGetArticleInput) -> Optional[ArticleResponse]:
    """
    Retrieve a specific article by its ID.
    Returns the full structured article or None.
    """
    article = get_article(input.article_id)
    if not article:
        return None

    return ArticleResponse(
        article_id=article.article_id,
        category=article.category,
        product=article.product,
        device_type=article.device_type,
        intent=article.intent,
        direct_answer=article.direct_answer,
        recommended_steps=article.recommended_steps,
        optional_steps=article.optional_steps,
        resolution_criteria=article.resolution_criteria,
        escalation_condition=article.escalation_condition,
        evidence_to_collect=article.evidence_to_collect,
    )


def kb_get_companions(input: KBGetCompanionsInput) -> CompanionsResponse:
    """
    Get all co-retrieval companion articles for a given article (recursive BFS).
    """
    co_result = expand_co_retrieval(
        [input.article_id],
        max_depth=CO_RETRIEVAL_MAX_DEPTH,
        exclude_ids={input.article_id},
    )
    results: list[ArticleResponse] = []

    for cid in co_result.companion_ids:
        article = get_article(cid)
        if article:
            results.append(ArticleResponse(
                article_id=article.article_id,
                category=article.category,
                product=article.product,
                device_type=article.device_type,
                intent=article.intent,
                direct_answer=article.direct_answer,
                recommended_steps=article.recommended_steps,
                optional_steps=article.optional_steps,
                resolution_criteria=article.resolution_criteria,
                escalation_condition=article.escalation_condition,
                evidence_to_collect=article.evidence_to_collect,
            ))

    return CompanionsResponse(
        article_id=input.article_id,
        companions=results,
        ordered_companion_ids=co_result.companion_ids,
        unresolved_ids=co_result.unresolved_ids,
        cycles_skipped=len(co_result.cycles_skipped),
        max_depth=CO_RETRIEVAL_MAX_DEPTH,
    )


def kb_diagnostics() -> DiagnosticsResponse:
    """
    Get health and statistics for the KB retrieval system.
    """
    conn = _get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) as cnt FROM articles").fetchone()["cnt"]
        rules = conn.execute("SELECT COUNT(*) as cnt FROM co_retrieval_rules").fetchone()["cnt"]
        terms = conn.execute("SELECT COUNT(*) as cnt FROM search_terms").fetchone()["cnt"]

        device_rows = conn.execute(
            "SELECT DISTINCT device_type FROM articles WHERE device_type != ''"
        ).fetchall()
        devices = [r["device_type"] for r in device_rows]

        category_rows = conn.execute(
            "SELECT DISTINCT category FROM articles WHERE category != ''"
        ).fetchall()
        categories = [r["category"] for r in category_rows]

        recent = conn.execute(
            "SELECT COUNT(*) as cnt FROM retrieval_logs WHERE timestamp > datetime('now', '-1 hour')"
        ).fetchone()["cnt"]

        return DiagnosticsResponse(
            total_articles=total,
            co_retrieval_rules=rules,
            search_terms_count=terms,
            device_types=devices,
            categories=categories,
            recent_queries=recent,
            co_retrieval_max_depth=CO_RETRIEVAL_MAX_DEPTH,
            retrieval_method_default=RAG_RETRIEVAL_METHOD,
        )
    finally:
        conn.close()
