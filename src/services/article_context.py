"""
Build ordered LLM context blocks from primary + companion articles.

Primary procedures come first; related companion procedures follow in
BFS discovery order with explicit continuation labels.
"""
from __future__ import annotations

from langchain_core.documents import Document

from src.models.article_schema import CanonicalArticle
from src.services.kb_database import get_article


def _format_article_sections(article: CanonicalArticle) -> str:
    sections: list[str] = []
    if article.direct_answer:
        sections.append(f"Direct Answer: {article.direct_answer}")
    if article.recommended_steps:
        steps = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(article.recommended_steps))
        sections.append(f"Recommended Steps:\n{steps}")
    if article.optional_steps:
        steps = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(article.optional_steps))
        sections.append(f"Optional Steps:\n{steps}")
    if article.resolution_criteria:
        sections.append(f"Resolution Confirmed When: {article.resolution_criteria}")
    if article.escalation_condition:
        sections.append(f"Escalate When: {article.escalation_condition}")
    if article.evidence_to_collect:
        sections.append(f"Evidence To Collect: {article.evidence_to_collect}")
    return "\n\n".join(sections) if sections else article.raw_body


def _structured_document(
    article: CanonicalArticle,
    label: str,
    retrieval_method: str = "hybrid",
) -> Document:
    body = _format_article_sections(article)
    content = f"{label}\n\n{body}"
    return Document(
        page_content=content,
        metadata={
            "article_id": article.article_id,
            "category": article.category,
            "product": article.product,
            "device_type": article.device_type,
            "intent": article.intent,
            "source_priority": "primary",
            "doc_type": "kb_article",
            "retrieval_method": retrieval_method,
            "context_role": "primary" if "PRIMARY" in label else "companion",
        },
    )


def _fallback_document(doc: Document, label: str) -> Document:
    """Wrap a vector/Qdrant document with a context label."""
    content = f"{label}\n\n{doc.page_content}"
    meta = dict(doc.metadata)
    meta["context_role"] = "primary" if "PRIMARY" in label else "companion"
    return Document(page_content=content, metadata=meta)


def build_ordered_context(
    primary_docs: list[Document],
    companion_ids: list[str],
    retrieval_method: str = "hybrid",
) -> list[Document]:
    """
    Build LLM context: primary articles first, then companions in BFS order.

    Prefers SQLite structured fields when available; falls back to
    primary_docs page_content for articles without SQLite rows.
    """
    ordered: list[Document] = []
    seen: set[str] = set()

    for doc in primary_docs:
        aid = doc.metadata.get("article_id", "")
        if aid:
            seen.add(aid)
            article = get_article(aid)
            if article:
                ordered.append(
                    _structured_document(
                        article,
                        "PRIMARY PROCEDURE",
                        retrieval_method=retrieval_method,
                    )
                )
            else:
                ordered.append(_fallback_document(doc, "PRIMARY PROCEDURE"))
        else:
            ordered.append(_fallback_document(doc, "PRIMARY PROCEDURE"))

    for cid in companion_ids:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        article = get_article(cid)
        if article:
            ordered.append(
                _structured_document(
                    article,
                    "CONTINUE WITH RELATED PROCEDURE (after primary steps)",
                    retrieval_method=retrieval_method,
                )
            )
        else:
            # Companion in rules but missing from SQLite — skip (logged by expander)
            continue

    return ordered
