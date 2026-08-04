"""Lazy image extraction bootstrap.

Called once on agent process start (FastAPI + Streamlit). If the SQLite
`images` table is empty (no extraction has ever run for this checkout),
runs the full pipeline for all KB sources so image-derived text is
available inside RAG answers.

If images already exist, this is a cheap no-op (single COUNT query).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)

_DB_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "kb_structured.db"
    )
)

_ENSURE_LOCK = threading.Lock()
_ENSURED = False


def images_db_ready() -> bool:
    """Return True if the images table exists and has at least one row."""
    if not os.path.exists(_DB_PATH):
        return False
    try:
        conn = sqlite3.connect(_DB_PATH)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='images'"
            ).fetchone()
            if not row:
                return False
            count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
            return count > 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("[IMAGES ENSURE] DB check failed: %s", exc)
        return False


def ensure_images_extracted(source: str = "all") -> None:
    """Run the image pipeline once if images DB is empty.

    Safe to call from FastAPI startup and Streamlit first render. Uses a
    process-level flag + lock so concurrent workers don't double-run.
    Failures are logged but never raised — chat must keep working even
    if Word/LibreOffice or OpenAI is unavailable.
    """
    global _ENSURED
    if _ENSURED:
        return

    with _ENSURE_LOCK:
        if _ENSURED:
            return

        if images_db_ready():
            logger.info("[IMAGES ENSURE] Images already extracted — skip.")
            _ENSURED = True
            return

        logger.warning(
            "[IMAGES ENSURE] No images found in %s — starting extraction pipeline "
            "for source=%s. First-time run may take several minutes.",
            _DB_PATH,
            source,
        )

        try:
            from src.services.images.pipeline import run_image_pipeline

            sources = ["v22", "bible"] if source == "all" else [source]
            for src in sources:
                try:
                    run_image_pipeline(source=src)
                except Exception as exc:
                    logger.error(
                        "[IMAGES ENSURE] Extraction failed for source=%s: %s. "
                        "Chat will continue text-only for this source.",
                        src,
                        exc,
                    )
            logger.info("[IMAGES ENSURE] Extraction pipeline finished.")
        except Exception as exc:
            logger.error(
                "[IMAGES ENSURE] Pipeline import/bootstrap failed: %s. "
                "Answers will be text-only.",
                exc,
            )
        finally:
            _ENSURED = True
