"""Deduplicate and filter extracted images.

Rules:
  - SHA256 checksum match -> keep first, discard rest
  - Width or height < 80px -> discard (logos, icons)
  - Aspect ratio > 10:1 or < 1:10 -> discard (headers/footers/dividers)
  - File size < 5KB -> discard (decorative)
"""
from __future__ import annotations

import logging
import os

from src.services.images.extractor import ExtractedImage

logger = logging.getLogger(__name__)

_MIN_DIMENSION = 80
_MAX_ASPECT_RATIO = 10.0
_MIN_FILE_SIZE = 5 * 1024  # 5 KB


def deduplicate_images(images: list[ExtractedImage]) -> list[ExtractedImage]:
    """Filter and deduplicate a batch of extracted images.

    Returns only images that pass all quality checks with no duplicate checksums.
    Removes discarded files from disk.
    """
    seen_checksums: set[str] = set()
    kept: list[ExtractedImage] = []
    removed = 0

    for img in images:
        reason = _should_discard(img, seen_checksums)
        if reason:
            _remove_file(img.file_path)
            removed += 1
            continue

        seen_checksums.add(img.checksum)
        kept.append(img)

    logger.info(
        "[DEDUPE] Kept %d / %d images (removed %d duplicates/junk)",
        len(kept), len(images), removed,
    )
    return kept


def _should_discard(img: ExtractedImage, seen: set[str]) -> str | None:
    if img.checksum in seen:
        return "duplicate"

    if img.width < _MIN_DIMENSION or img.height < _MIN_DIMENSION:
        return "too_small"

    if img.file_size < _MIN_FILE_SIZE:
        return "tiny_file"

    aspect = max(img.width, img.height) / max(min(img.width, img.height), 1)
    if aspect > _MAX_ASPECT_RATIO:
        return "extreme_aspect"

    return None


def _remove_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
