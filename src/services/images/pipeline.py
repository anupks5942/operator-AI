"""One-shot image extraction pipeline orchestrator.

Usage:
    uv run python -m src.services.images.pipeline --source v22
    uv run python -m src.services.images.pipeline --source bible
    uv run python -m src.services.images.pipeline --source all
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import sqlite3

import fitz  # PyMuPDF

from src.services.images.pdf_prep import convert_docx_to_pdf
from src.services.images.empty_page import is_empty_page
from src.services.images.case_mapper import (
    build_v22_page_map,
    build_bible_page_map,
    get_article_for_page,
)
from src.services.images.extractor import extract_page_images, ExtractedImage
from src.services.images.dedupe import deduplicate_images
from src.services.images.captioner import caption_images, CaptionResult
from src.services.images.search_terms import extract_search_terms

logger = logging.getLogger(__name__)

_KB_DIR = "KB"
_V22_MARKERS = ("ai_support_knowledge_base", "ai support knowledge base")
_BIBLE_MARKERS = ("bible",)


def _find_source_docx(source: str) -> str | None:
    """Find the DOCX file for a given source type."""
    if not os.path.exists(_KB_DIR):
        return None
    for filename in os.listdir(_KB_DIR):
        if not filename.endswith(".docx"):
            continue
        name_lower = filename.lower().replace("-", "_").replace(" ", "_")
        if source == "v22" and any(m in name_lower for m in _V22_MARKERS):
            return os.path.join(_KB_DIR, filename)
        if source == "bible" and any(m in name_lower for m in _BIBLE_MARKERS):
            return os.path.join(_KB_DIR, filename)
    return None


def _get_db_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "kb_structured.db")
    )


def _get_images_dir(source: str) -> str:
    from src.config import _env_str
    base = _env_str("KB_IMAGES_DIR", "./kb_images")
    return os.path.join(base, source)


def _log_empty_page(db_path: str, source_doc: str, page_number: int, reason: str):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO pdf_page_skip_log (source_doc, page_number, reason) VALUES (?, ?, ?)",
            (source_doc, page_number, reason),
        )
        conn.commit()
    finally:
        conn.close()


def _store_image(
    db_path: str,
    image_id: str,
    source_doc: str,
    img: ExtractedImage,
    caption_result: CaptionResult | None,
    article_ids: list[str],
    terms: list[str],
):
    conn = sqlite3.connect(db_path)
    try:
        caption = caption_result.caption if caption_result else ""
        visual_summary = caption_result.visual_summary if caption_result else ""
        image_type = caption_result.image_type if caption_result else "screenshot"

        conn.execute("""
            INSERT OR REPLACE INTO images
            (image_id, source_doc, file_path, checksum, image_type, caption, visual_summary,
             width, height, format, file_size, page_number, sequence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            image_id, source_doc, img.file_path, img.checksum, image_type,
            caption, visual_summary, img.width, img.height, img.format,
            img.file_size, img.page_number, img.sequence,
        ))

        for aid in article_ids:
            conn.execute(
                "INSERT OR REPLACE INTO image_case_map (image_id, article_id, is_primary) VALUES (?, ?, 1)",
                (image_id, aid),
            )

        for term in terms:
            conn.execute(
                "INSERT OR REPLACE INTO image_search_terms (image_id, term) VALUES (?, ?)",
                (image_id, term),
            )

        conn.commit()
    finally:
        conn.close()


def run_image_pipeline(
    source: str,
    caption_limit: int | None = None,
    skip_captions: bool = False,
    strict_empty: bool = False,
):
    """Run the full extraction pipeline for one source document.

    Args:
        source: 'v22' or 'bible'
        caption_limit: limit GPT-4o calls (for testing). None = unlimited.
        skip_captions: skip GPT-4o entirely (faster, no captions).
        strict_empty: enable pixel-level blank page detection.
    """
    from src.services.kb_database import initialize_database
    initialize_database()

    db_path = _get_db_path()
    images_dir = _get_images_dir(source)
    os.makedirs(images_dir, exist_ok=True)

    docx_path = _find_source_docx(source)
    if not docx_path:
        logger.error("[PIPELINE] No DOCX found for source=%s in %s", source, _KB_DIR)
        return

    logger.info("[PIPELINE] Starting image pipeline for source=%s, file=%s", source, docx_path)

    # Step 1: DOCX -> PDF
    pdf_path = convert_docx_to_pdf(docx_path)
    logger.info("[PIPELINE] PDF ready: %s", pdf_path)

    # Step 2: Build case/page map
    if source == "v22":
        page_map = build_v22_page_map(pdf_path)
    else:
        page_map = build_bible_page_map(pdf_path)

    # Step 3: Extract images page by page
    doc = fitz.open(pdf_path)
    all_images: list[tuple[ExtractedImage, list[str]]] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1

        skip_reason = is_empty_page(page, strict=strict_empty)
        if skip_reason:
            _log_empty_page(db_path, source, page_num, skip_reason)
            continue

        article_ids = get_article_for_page(page_map, page_num)
        prefix = f"{source}_{article_ids[0] if article_ids else 'UNLINKED'}"

        extracted = extract_page_images(page, page_num, images_dir, prefix, doc)
        for img in extracted:
            all_images.append((img, article_ids))

    total_pages = len(doc)
    doc.close()
    logger.info("[PIPELINE] Extracted %d raw images from %d pages", len(all_images), total_pages)

    # Step 4: Deduplicate
    raw_imgs = [img for img, _ in all_images]
    kept_imgs = deduplicate_images(raw_imgs)
    kept_checksums = {img.checksum for img in kept_imgs}

    filtered_images = [(img, aids) for img, aids in all_images if img.checksum in kept_checksums]

    # Step 5: Caption (GPT-4o)
    captions: dict[str, CaptionResult] = {}
    if not skip_captions:
        to_caption = kept_imgs[:caption_limit] if caption_limit else kept_imgs
        captions = caption_images(to_caption, db_path)

    # Step 6: Store in DB
    stored = 0
    for img, article_ids in filtered_images:
        if img.checksum not in kept_checksums:
            continue
        kept_checksums.discard(img.checksum)  # first occurrence only

        caption_result = captions.get(img.checksum)
        terms = extract_search_terms(caption_result) if caption_result else []

        aid_part = article_ids[0] if article_ids else "UNLINKED"
        image_id = f"{source}_{aid_part}_p{img.page_number}_i{img.sequence}"

        _store_image(db_path, image_id, source, img, caption_result, article_ids, terms)
        stored += 1

    logger.info("[PIPELINE] Stored %d images for source=%s", stored, source)


def main(argv: list[str] | None = None):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="KB Image Extraction Pipeline")
    parser.add_argument("--source", choices=["v22", "bible", "all"], default="all")
    parser.add_argument("--caption-limit", type=int, default=None, help="Max images to caption (for testing)")
    parser.add_argument("--skip-captions", action="store_true", help="Skip GPT-4o captioning entirely")
    parser.add_argument("--strict-empty", action="store_true", help="Enable pixel-level blank detection")
    args = parser.parse_args(argv)

    sources = ["v22", "bible"] if args.source == "all" else [args.source]

    for source in sources:
        run_image_pipeline(
            source=source,
            caption_limit=args.caption_limit,
            skip_captions=args.skip_captions,
            strict_empty=args.strict_empty,
        )

    print("\nImage pipeline complete.")


if __name__ == "__main__":
    main()
