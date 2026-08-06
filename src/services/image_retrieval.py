"""Image retrieval layer — fetch images by case ID, search terms, or full visual bundle.

Reuses expand_co_retrieval() for linked-case image retrieval.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Optional

from src.services.co_retrieval import expand_co_retrieval
from src.config import CO_RETRIEVAL_MAX_DEPTH

logger = logging.getLogger(__name__)

_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kb_structured.db")
)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def filter_images_safe(
    images: list[dict],
    article_id: str = "",
    article_meta: dict | None = None,
) -> list[dict]:
    """Apply image safety rules per Brandon's v2.3 guidance.

    Drops images that are:
    - Outdated (review_status = 'outdated' or 'unapproved')
    - Product/device mismatch with the selected article
    - Flagged for text-image conflict

    Returns filtered list (may be shorter).
    """
    if not images:
        return []

    article_product = (article_meta or {}).get("product", "").lower()
    article_device = (article_meta or {}).get("device_type", "").lower()

    filtered: list[dict] = []
    for img in images:
        review = (img.get("review_status") or "approved").lower()
        if review in ("outdated", "unapproved"):
            logger.debug("[IMAGE_SAFETY] Dropped %s: review_status=%s", img.get("image_id"), review)
            continue

        if img.get("text_image_conflict"):
            logger.debug("[IMAGE_SAFETY] Dropped %s: text_image_conflict", img.get("image_id"))
            continue

        # Device/product mismatch check (only if article has specifics)
        if article_product and article_device:
            img_articles = img.get("_registry_articles", [])
            if img_articles and article_id and article_id not in img_articles:
                logger.debug("[IMAGE_SAFETY] Dropped %s: not linked to %s", img.get("image_id"), article_id)
                continue

        filtered.append(img)

    if len(filtered) < len(images):
        logger.info(
            "[IMAGE_SAFETY] Filtered %d -> %d images for article=%s",
            len(images), len(filtered), article_id,
        )
    return filtered


def get_case_images(
    article_id: str,
    include_linked: bool = True,
    limit: int = 12,
) -> list[dict]:
    """Get images for a case ID. Optionally includes linked-case images via BFS co-retrieval."""
    start = time.time()
    conn = _get_conn()
    try:
        primary_images = _fetch_images_for_article(conn, article_id)

        linked_images: list[dict] = []
        companion_ids: list[str] = []
        if include_linked:
            co_result = expand_co_retrieval(
                [article_id],
                max_depth=CO_RETRIEVAL_MAX_DEPTH,
                exclude_ids={article_id},
            )
            companion_ids = co_result.companion_ids
            for cid in companion_ids:
                linked = _fetch_images_for_article(conn, cid)
                for img in linked:
                    img["is_primary"] = False
                    img["linked_from"] = article_id
                linked_images.extend(linked)

        for img in primary_images:
            img["is_primary"] = True

        all_images = primary_images + linked_images
        result = all_images[:limit]

        _log_retrieval(conn, article_id, result, companion_ids, time.time() - start)
        return result
    finally:
        conn.close()


def search_case_images(
    query: str,
    device: str = "",
    image_type: str = "",
    limit: int = 12,
) -> list[dict]:
    """Search images by search terms, optionally filtered by device or image type."""
    start = time.time()
    conn = _get_conn()
    try:
        terms = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not terms:
            return []

        placeholders = ",".join("?" for _ in terms)
        sql = f"""
            SELECT DISTINCT i.* FROM images i
            JOIN image_search_terms ist ON i.image_id = ist.image_id
            WHERE ist.term IN ({placeholders})
        """
        params: list = list(terms)

        if image_type:
            sql += " AND i.image_type = ?"
            params.append(image_type)

        sql += " ORDER BY i.page_number LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = [_row_to_dict(r) for r in rows]

        if device:
            device_lower = device.lower()
            filtered = []
            for img in results:
                article_ids = _get_article_ids_for_image(conn, img["image_id"])
                for aid in article_ids:
                    article_row = conn.execute(
                        "SELECT device_type FROM articles WHERE article_id = ?", (aid,)
                    ).fetchone()
                    if article_row and device_lower in (article_row["device_type"] or "").lower():
                        filtered.append(img)
                        break
                else:
                    filtered.append(img)
            results = filtered[:limit]

        latency = time.time() - start
        logger.info("[IMAGE_RETRIEVAL] search '%s' -> %d results in %.1fms", query, len(results), latency * 1000)
        return results
    finally:
        conn.close()


def get_case_visual_bundle(article_id: str) -> dict:
    """Get the full visual bundle: article text + primary images + companion images ordered."""
    conn = _get_conn()
    try:
        article_row = conn.execute(
            "SELECT * FROM articles WHERE article_id = ?", (article_id,)
        ).fetchone()

        article_data = _row_to_dict(article_row) if article_row else None
        images = get_case_images(article_id, include_linked=True)

        return {
            "article_id": article_id,
            "article": article_data,
            "images": images,
            "primary_count": sum(1 for i in images if i.get("is_primary")),
            "companion_count": sum(1 for i in images if not i.get("is_primary")),
        }
    finally:
        conn.close()


def _fetch_images_for_article(conn: sqlite3.Connection, article_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT i.* FROM images i
        JOIN image_case_map icm ON i.image_id = icm.image_id
        WHERE icm.article_id = ?
        ORDER BY i.page_number, i.sequence
    """, (article_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def _get_article_ids_for_image(conn: sqlite3.Connection, image_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT article_id FROM image_case_map WHERE image_id = ?", (image_id,)
    ).fetchall()
    return [r["article_id"] for r in rows]


def _log_retrieval(
    conn: sqlite3.Connection,
    article_id: str,
    images: list[dict],
    linked_cases: list[str],
    elapsed: float,
):
    try:
        conn.execute("""
            INSERT INTO image_retrieval_logs
            (query, article_ids_json, image_ids_json, pages_json, linked_cases_json, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            article_id,
            json.dumps([article_id]),
            json.dumps([i.get("image_id", "") for i in images]),
            json.dumps(list({i.get("page_number", 0) for i in images})),
            json.dumps(linked_cases),
            elapsed * 1000,
        ))
        conn.commit()
    except Exception:
        pass
