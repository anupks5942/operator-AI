"""PageIndex — Hierarchical tree routing for vectorless retrieval.

Routes a query + hints to candidate article IDs by traversing:
    root -> part -> category -> product -> article

Used as a pre-filter before keyword/intent matching in vectorless_retrieve().
"""
from __future__ import annotations

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kb_structured.db")
)


def route(
    query: str,
    hints: dict | None = None,
    db_path: str | None = None,
    max_results: int = 20,
) -> list[str]:
    """Route a query through the PageIndex tree to candidate article IDs.

    Args:
        query: user query text (currently unused; routing by hints)
        hints: dict with optional keys: category, product, device_type, intent, article_id
        db_path: override SQLite path
        max_results: cap on returned article IDs

    Returns:
        List of article_id strings matched by hierarchical traversal.
        Empty list means "no PageIndex match — fall through to keyword search".
    """
    db = db_path or _DB_PATH
    hints = hints or {}

    if not os.path.exists(db):
        return []

    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM page_index_nodes").fetchone()[0]
        if count == 0:
            return []

        # Direct article_id hit
        if hints.get("article_id"):
            row = conn.execute(
                "SELECT article_id FROM page_index_nodes WHERE article_id = ? AND level = 'article'",
                (hints["article_id"],),
            ).fetchone()
            if row:
                return [row[0]]

        # Build filter from hints
        category = hints.get("category", "").strip()
        product = hints.get("product", "").strip()

        if not category and not product:
            return []

        # Match category nodes
        if category and product:
            rows = conn.execute("""
                SELECT pn.article_id
                FROM page_index_nodes pn
                JOIN page_index_nodes prod ON pn.parent_id = prod.node_id
                JOIN page_index_nodes cat ON prod.parent_id = cat.node_id
                WHERE pn.level = 'article'
                  AND cat.label LIKE ?
                  AND prod.label LIKE ?
                LIMIT ?
            """, (f"%{category}%", f"%{product}%", max_results)).fetchall()
        elif category:
            rows = conn.execute("""
                SELECT pn.article_id
                FROM page_index_nodes pn
                JOIN page_index_nodes prod ON pn.parent_id = prod.node_id
                JOIN page_index_nodes cat ON prod.parent_id = cat.node_id
                WHERE pn.level = 'article'
                  AND cat.label LIKE ?
                LIMIT ?
            """, (f"%{category}%", max_results)).fetchall()
        else:
            rows = conn.execute("""
                SELECT pn.article_id
                FROM page_index_nodes pn
                JOIN page_index_nodes prod ON pn.parent_id = prod.node_id
                WHERE pn.level = 'article'
                  AND prod.label LIKE ?
                LIMIT ?
            """, (f"%{product}%", max_results)).fetchall()

        results = [r[0] for r in rows if r[0]]
        if results:
            logger.debug("[PAGE_INDEX] Route matched %d articles for hints=%s", len(results), hints)
        return results

    except Exception as e:
        logger.warning("[PAGE_INDEX] Route failed: %s", e)
        return []
    finally:
        conn.close()


def get_leaf_for_article(article_id: str, db_path: str | None = None) -> str:
    """Return the PageIndex leaf node_id for an article (for logging)."""
    db = db_path or _DB_PATH
    if not os.path.exists(db):
        return ""
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT node_id FROM page_index_nodes WHERE article_id = ? AND level = 'article'",
            (article_id,),
        ).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()
