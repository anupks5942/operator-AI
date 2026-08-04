"""Centralized Qdrant client factory with retry, timeout, and health checks.

Used by both data_injection/inject.py and src/services/rag_service.py.
"""
from __future__ import annotations

import logging
import time

from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15
_MAX_RETRIES = 3
_RETRY_DELAY_BASE = 1.0


def get_qdrant_client(path: str, timeout: int = _DEFAULT_TIMEOUT) -> QdrantClient:
    """Create a QdrantClient with configured timeout.

    For local on-disk mode, timeout mainly applies to internal operations.
    Retries are handled at the operation level via retry_operation().
    """
    client = QdrantClient(path=path, timeout=timeout)
    return client


def check_qdrant_health(client: QdrantClient, collection: str) -> bool:
    """Verify collection exists and is accessible. Logs stats.

    Returns True if healthy, False otherwise.
    """
    try:
        if not client.collection_exists(collection):
            logger.error("[QDRANT_HEALTH] Collection '%s' does not exist", collection)
            return False

        info = client.get_collection(collection)
        point_count = info.points_count or 0
        indexed_fields = info.payload_schema or {}

        logger.info(
            "[QDRANT_HEALTH] Collection '%s' OK — %d points, %d payload indexes",
            collection, point_count, len(indexed_fields),
        )

        if indexed_fields:
            for field_name in indexed_fields:
                logger.info("[QDRANT_HEALTH]   Index: %s", field_name)

        if point_count == 0:
            logger.warning("[QDRANT_HEALTH] Collection is empty — run data_injection to populate")

        return True
    except Exception as exc:
        logger.error("[QDRANT_HEALTH] Health check failed: %s", exc)
        return False


def retry_operation(func, *args, max_retries: int = _MAX_RETRIES, **kwargs):
    """Execute a Qdrant operation with exponential backoff retries.

    Raises the last exception if all retries fail.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = _RETRY_DELAY_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "[QDRANT_RETRY] Attempt %d/%d failed (%s), retrying in %.1fs...",
                    attempt, max_retries, exc, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "[QDRANT_RETRY] All %d attempts failed. Last error: %s",
                    max_retries, exc,
                )
    raise last_exc
