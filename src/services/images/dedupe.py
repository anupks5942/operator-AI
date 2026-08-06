"""Deduplicate and filter extracted images.

Rules:
  - SHA256 checksum match -> keep first, discard rest
  - Perceptual hash match -> same stable_id (IMG-SW-####)
  - Width or height < 80px -> discard (logos, icons)
  - Aspect ratio > 10:1 or < 1:10 -> discard (headers/footers/dividers)
  - File size < 5KB -> discard (decorative)
"""
from __future__ import annotations

import logging
import os
import sqlite3

from src.services.images.extractor import ExtractedImage

logger = logging.getLogger(__name__)

_MIN_DIMENSION = 80
_MAX_ASPECT_RATIO = 10.0
_MIN_FILE_SIZE = 5 * 1024  # 5 KB

_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "kb_structured.db")
)


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


def compute_phash(file_path: str) -> str:
    """Compute perceptual hash for an image file. Returns hex string."""
    try:
        import imagehash
        from PIL import Image
        img = Image.open(file_path)
        return str(imagehash.phash(img))
    except Exception as e:
        logger.debug("[DEDUPE] phash failed for %s: %s", file_path, e)
        return ""


def assign_stable_id(checksum: str, phash: str, db_path: str | None = None) -> str:
    """Assign or retrieve a stable IMG-SW-#### ID for an image.

    Two images with the same phash (even different byte hash) share a stable ID.
    If the image is already in the registry (from Brandon's v2.3), use that ID.
    Otherwise, auto-assign the next available IMG-SW-#### in sequence.
    """
    db = db_path or _DB_PATH
    conn = sqlite3.connect(db)
    try:
        # Check if already assigned via checksum
        row = conn.execute(
            "SELECT stable_id FROM images WHERE checksum = ? AND stable_id IS NOT NULL AND stable_id != ''",
            (checksum,),
        ).fetchone()
        if row:
            return row[0]

        # Check if phash matches an existing image
        if phash:
            row = conn.execute(
                "SELECT stable_id FROM images WHERE phash = ? AND stable_id IS NOT NULL AND stable_id != ''",
                (phash,),
            ).fetchone()
            if row:
                return row[0]

        # Auto-assign next available IMG-SW-####
        row = conn.execute("""
            SELECT stable_id FROM images
            WHERE stable_id LIKE 'IMG-SW-%'
            ORDER BY stable_id DESC LIMIT 1
        """).fetchone()

        if row:
            last_num = int(row[0].replace("IMG-SW-", ""))
            next_num = last_num + 1
        else:
            # Check registry for highest used
            row = conn.execute("""
                SELECT image_id FROM image_asset_registry
                WHERE image_id LIKE 'IMG-SW-%'
                ORDER BY image_id DESC LIMIT 1
            """).fetchone()
            if row:
                last_num = int(row[0].replace("IMG-SW-", ""))
                next_num = last_num + 1
            else:
                next_num = 1

        stable_id = f"IMG-SW-{next_num:04d}"
        return stable_id
    finally:
        conn.close()


def assign_stable_ids_to_all(db_path: str | None = None) -> int:
    """One-time migration: assign stable_id + phash to all existing images."""
    db = db_path or _DB_PATH
    conn = sqlite3.connect(db)
    count = 0
    try:
        rows = conn.execute(
            "SELECT image_id, file_path, checksum, stable_id, phash FROM images ORDER BY page_number, sequence"
        ).fetchall()

        for image_id, file_path, checksum, existing_stable, existing_phash in rows:
            if existing_stable:
                continue

            phash = existing_phash or ""
            if not phash and file_path and os.path.exists(file_path):
                phash = compute_phash(file_path)

            stable_id = assign_stable_id(checksum, phash, db)
            conn.execute(
                "UPDATE images SET stable_id = ?, phash = ? WHERE image_id = ?",
                (stable_id, phash, image_id),
            )
            count += 1

        conn.commit()
        logger.info("[DEDUPE] Assigned stable IDs to %d images", count)
    finally:
        conn.close()
    return count
