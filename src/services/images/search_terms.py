"""Extract searchable terms from image captions and visual summaries.

Extracts: UI labels, button names, device names, error messages, product names, action terms.
"""
from __future__ import annotations

import re
import logging

from src.services.images.captioner import CaptionResult

logger = logging.getLogger(__name__)

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "it", "its", "this", "that", "these",
    "those", "my", "your", "i", "me", "we", "they", "and", "or", "but",
    "not", "no", "so", "if", "then", "when", "what", "which", "who", "how",
    "where", "all", "each", "every", "any", "some", "just", "very", "also",
    "there", "image", "shows", "showing", "visible", "displayed", "screen",
}

_DEVICE_TERMS = {
    "pos", "kiosk", "hub", "card reader", "control board", "relay",
    "serial", "spyderwash", "setomatic", "printer", "router", "switch",
    "gateway", "modem", "antenna", "display", "keypad", "coin",
}

_QUOTED_RE = re.compile(r'"([^"]+)"')
_LABEL_RE = re.compile(r"'([^']+)'")


def extract_search_terms(caption_result: CaptionResult) -> list[str]:
    """Extract unique searchable terms from a caption and visual summary."""
    terms: set[str] = set()

    combined = f"{caption_result.caption} {caption_result.visual_summary}"

    for match in _QUOTED_RE.finditer(combined):
        term = match.group(1).strip().lower()
        if len(term) > 2:
            terms.add(term)

    for match in _LABEL_RE.finditer(combined):
        term = match.group(1).strip().lower()
        if len(term) > 2:
            terms.add(term)

    for device in _DEVICE_TERMS:
        if device in combined.lower():
            terms.add(device)

    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", combined)
    for word in words:
        w = word.lower()
        if w not in _STOP_WORDS and len(w) > 3:
            terms.add(w)

    terms.add(caption_result.image_type)

    return sorted(terms)
