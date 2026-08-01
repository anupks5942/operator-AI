"""
Recursive co-retrieval engine — BFS over SQLite co_retrieval_rules.

Supports multi-level case reference traversal with cycle prevention,
deduplication, and unresolved reference reporting.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from src.services.kb_database import get_article, get_companions

logger = logging.getLogger(__name__)


@dataclass
class CoRetrievalResult:
    """Result of recursive co-retrieval expansion."""

    seed_ids: list[str] = field(default_factory=list)
    ordered_ids: list[str] = field(default_factory=list)
    companion_ids: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    depth_by_id: dict[str, int] = field(default_factory=dict)
    unresolved_ids: list[str] = field(default_factory=list)
    cycles_skipped: list[tuple[str, str]] = field(default_factory=list)


def expand_co_retrieval(
    seed_article_ids: list[str],
    max_depth: int = 3,
    exclude_ids: set[str] | None = None,
) -> CoRetrievalResult:
    """
    BFS expansion of co-retrieval rules from seed article IDs.

    Args:
        seed_article_ids: Primary article IDs to expand from.
        max_depth: Maximum traversal depth (default 3).
        exclude_ids: IDs already in context (primary hits) — still traversed
            for edges but not duplicated in companion_ids.

    Returns:
        CoRetrievalResult with ordered companion chain and diagnostics.
    """
    exclude = set(exclude_ids or [])
    seeds = [sid for sid in seed_article_ids if sid]
    result = CoRetrievalResult(seed_ids=seeds)

    if not seeds or max_depth < 1:
        return result

    visited: set[str] = set(seeds) | exclude
    queue: deque[tuple[str, int]] = deque()

    for sid in seeds:
        queue.append((sid, 0))

    while queue:
        current_id, depth = queue.popleft()
        if depth >= max_depth:
            continue

        companion_ids = get_companions(current_id)
        for cid in companion_ids:
            if not cid:
                continue

            result.edges.append((current_id, cid))

            if cid in visited:
                result.cycles_skipped.append((current_id, cid))
                continue

            article = get_article(cid)
            if article is None:
                if cid not in result.unresolved_ids:
                    result.unresolved_ids.append(cid)
                continue

            visited.add(cid)
            child_depth = depth + 1
            result.depth_by_id[cid] = child_depth

            if cid not in exclude:
                result.companion_ids.append(cid)
                result.ordered_ids.append(cid)

            queue.append((cid, child_depth))

    if result.unresolved_ids:
        logger.warning(
            "[CO_RETRIEVAL] Unresolved companion IDs: %s",
            result.unresolved_ids,
        )
    if result.cycles_skipped:
        logger.info(
            "[CO_RETRIEVAL] Cycles skipped: %d",
            len(result.cycles_skipped),
        )

    logger.info(
        "[CO_RETRIEVAL] Expanded %d seeds → %d companions (depth≤%d, unresolved=%d)",
        len(seeds),
        len(result.companion_ids),
        max_depth,
        len(result.unresolved_ids),
    )

    return result
