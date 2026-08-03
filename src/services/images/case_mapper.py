"""Map PDF pages to article/case IDs.

v2.2: Uses ARTICLE START/END text markers found in PDF page text.
Bible: Builds synthetic section IDs from known section start markers.
"""
from __future__ import annotations

import logging
import re

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_ARTICLE_START_RE = re.compile(r"ARTICLE\s+START:\s*(KB-[A-Z]+-\d+)")
_ARTICLE_END_RE = re.compile(r"ARTICLE\s+END:\s*(KB-[A-Z]+-\d+)")

_BIBLE_SECTION_MARKERS = [
    ("BIBLE-TROUBLESHOOT", "Troubleshooting\nNetwork Issues"),
    ("BIBLE-OPERATOR", "Operator Portal"),
]
_BIBLE_OPERATOR_END = "Voiceover: SpyderWash Troubleshooting Guide"


def build_v22_page_map(pdf_path: str) -> dict[str, tuple[int, int]]:
    """Build article_id -> (start_page, end_page) from v2.2 PDF.

    Pages are 1-indexed.
    """
    doc = fitz.open(pdf_path)
    page_map: dict[str, tuple[int, int]] = {}
    open_articles: dict[str, int] = {}

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = page.get_text()
        page_num = page_idx + 1

        for match in _ARTICLE_START_RE.finditer(text):
            article_id = match.group(1)
            open_articles[article_id] = page_num

        for match in _ARTICLE_END_RE.finditer(text):
            article_id = match.group(1)
            start = open_articles.pop(article_id, page_num)
            page_map[article_id] = (start, page_num)

    for article_id, start in open_articles.items():
        page_map[article_id] = (start, len(doc))
        logger.warning("[CASE_MAPPER] Article %s never closed, assumed ends at last page", article_id)

    doc.close()
    logger.info("[CASE_MAPPER] v2.2 mapped %d articles to page ranges", len(page_map))
    return page_map


def build_bible_page_map(pdf_path: str) -> dict[str, tuple[int, int]]:
    """Build synthetic section IDs for Bible PDF.

    Returns BIBLE-TROUBLESHOOT-001..N and BIBLE-OPERATOR-001..N based on
    known section start markers from the existing parser.
    """
    doc = fitz.open(pdf_path)
    sections: list[tuple[str, int]] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = page.get_text()
        page_num = page_idx + 1

        for prefix, marker in _BIBLE_SECTION_MARKERS:
            if marker in text and not any(s[0].startswith(prefix) for s in sections):
                sections.append((prefix, page_num))

    page_map: dict[str, tuple[int, int]] = {}
    total_pages = len(doc)
    doc.close()

    for i, (prefix, start) in enumerate(sections):
        if i + 1 < len(sections):
            end = sections[i + 1][1] - 1
        else:
            end = total_pages

        chunk_size = 10
        section_num = 1
        for chunk_start in range(start, end + 1, chunk_size):
            chunk_end = min(chunk_start + chunk_size - 1, end)
            section_id = f"{prefix}-{section_num:03d}"
            page_map[section_id] = (chunk_start, chunk_end)
            section_num += 1

    logger.info("[CASE_MAPPER] Bible mapped %d synthetic sections", len(page_map))
    return page_map


def get_article_for_page(page_map: dict[str, tuple[int, int]], page_num: int) -> list[str]:
    """Return all article IDs whose page range includes the given page."""
    return [
        aid for aid, (start, end) in page_map.items()
        if start <= page_num <= end
    ]
