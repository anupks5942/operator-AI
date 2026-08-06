"""Map PDF pages to article/case IDs.

v2.3+: Uses Image Asset Registry (Brandon's explicit mapping) when available.
v2.2 fallback: ARTICLE START/END text markers found in PDF page text.
Bible: Builds synthetic section IDs from known section start markers.
"""
from __future__ import annotations

import logging
import re

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def get_articles_from_registry(image_stable_id: str) -> list[str]:
    """Look up article IDs for an image from the asset registry (v2.3+).

    Returns empty list if registry not populated or image not found.
    """
    try:
        from src.services.images.asset_registry import get_registry_articles_for_image
        return get_registry_articles_for_image(image_stable_id)
    except Exception:
        return []


def get_registry_description(image_stable_id: str) -> str:
    """Get Brandon's authored description for an image ID."""
    try:
        from src.services.images.asset_registry import get_registry_description as _get
        return _get(image_stable_id)
    except Exception:
        return ""

_ARTICLE_START_RE = re.compile(r"ARTICLE\s+START:\s*(KB-[A-Z0-9][\w-]*)")
_ARTICLE_END_RE = re.compile(r"ARTICLE\s+END:\s*(KB-[A-Z0-9][\w-]*)")


def map_paragraphs_to_pages(docx_path: str, pdf_path: str) -> dict[int, int]:
    """Map DOCX paragraph indices to PDF page numbers.

    Uses proportional mapping: paragraph position relative to total paragraphs
    maps to the same relative position in total PDF pages. Then refines by
    searching for ARTICLE START/END markers to anchor key positions.
    """
    import fitz
    from docx import Document

    doc = Document(docx_path)
    total_paras = len(doc.paragraphs)

    pdf_doc = fitz.open(pdf_path)
    total_pages = len(pdf_doc)

    # Build anchor points: paragraph indices where ARTICLE START appears
    anchors: list[tuple[int, int]] = []  # (para_idx, page_number)

    article_start_paras: dict[str, int] = {}
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        m = _ARTICLE_START_RE.search(text)
        if m:
            article_start_paras[m.group(1)] = i

    # Find same markers in PDF to get page numbers
    for page_idx in range(total_pages):
        page_text = pdf_doc[page_idx].get_text()
        for m in _ARTICLE_START_RE.finditer(page_text):
            aid = m.group(1)
            if aid in article_start_paras:
                anchors.append((article_start_paras[aid], page_idx + 1))

    pdf_doc.close()

    # Sort anchors by paragraph index
    anchors.sort(key=lambda x: x[0])

    def _estimate_page(para_idx: int) -> int:
        """Estimate page for a paragraph using anchor interpolation."""
        if not anchors:
            return max(1, int((para_idx / max(total_paras, 1)) * total_pages) + 1)

        # Before first anchor
        if para_idx <= anchors[0][0]:
            ratio = para_idx / max(anchors[0][0], 1)
            return max(1, int(ratio * anchors[0][1]))

        # After last anchor
        if para_idx >= anchors[-1][0]:
            remaining_paras = total_paras - anchors[-1][0]
            remaining_pages = total_pages - anchors[-1][1]
            offset = para_idx - anchors[-1][0]
            extra = int((offset / max(remaining_paras, 1)) * remaining_pages)
            return min(total_pages, anchors[-1][1] + extra)

        # Between two anchors — interpolate
        for i in range(len(anchors) - 1):
            if anchors[i][0] <= para_idx <= anchors[i + 1][0]:
                para_span = anchors[i + 1][0] - anchors[i][0]
                page_span = anchors[i + 1][1] - anchors[i][1]
                ratio = (para_idx - anchors[i][0]) / max(para_span, 1)
                return anchors[i][1] + int(ratio * page_span)

        return max(1, int((para_idx / max(total_paras, 1)) * total_pages) + 1)

    # Build the full mapping for every paragraph that might have an image
    para_to_page: dict[int, int] = {}
    for i in range(total_paras):
        para_to_page[i] = _estimate_page(i)

    logger.info(
        "[CASE_MAPPER] Mapped %d paragraphs to pages using %d anchors",
        total_paras, len(anchors),
    )
    return para_to_page

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
