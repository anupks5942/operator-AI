"""Empty page detection — pages with no meaningful content are skipped from storage."""
from __future__ import annotations

import logging
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 20
_MIN_DRAWINGS = 3
_BLANK_PIXEL_THRESHOLD = 0.01  # < 1% non-white pixels = blank


def is_empty_page(page: fitz.Page, strict: bool = False) -> Optional[str]:
    """Return skip reason if page is empty, else None.

    Checks in order of cost (cheapest first):
      1. text + images + drawings (no rendering)
      2. minimal-content threshold
      3. pixel-level blank check (only if strict=True)
    """
    text = page.get_text().strip()
    images = page.get_images(full=True)
    drawings = page.get_drawings()

    if not text and not images and not drawings:
        return "no_content"

    if len(text) < _MIN_TEXT_LENGTH and not images and len(drawings) < _MIN_DRAWINGS:
        return "minimal_content"

    if strict and not images:
        pix = page.get_pixmap(dpi=72)
        samples = pix.samples
        total_pixels = pix.width * pix.height
        non_white = sum(1 for i in range(0, len(samples), pix.n) if any(samples[i + c] < 250 for c in range(min(pix.n, 3))))
        ratio = non_white / total_pixels if total_pixels else 0
        if ratio < _BLANK_PIXEL_THRESHOLD:
            return "blank_pixels"

    return None
