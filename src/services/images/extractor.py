"""Image extraction from PDF pages and DOCX files.

Three modes:
  1. DOCX direct: extract images from word/media/ via python-docx (primary).
  2. PDF embedded: pull raster images from PDF xref objects.
  3. Full-page render: 200 DPI fallback for tables/diagrams only.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
from dataclasses import dataclass, field

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)

_RENDER_DPI = 200
_MIN_EMBEDDED_SIZE = 80  # skip embedded images smaller than 80px on either axis
_MIN_DOCX_IMAGE_SIZE = 80  # skip DOCX images smaller than 80px


@dataclass
class ExtractedImage:
    """Metadata for a single extracted image."""
    file_path: str
    page_number: int
    sequence: int
    width: int
    height: int
    format: str
    file_size: int
    checksum: str
    source: str = "embedded"  # "embedded" or "fullpage"


def extract_docx_images(
    docx_path: str,
    output_dir: str,
    prefix: str = "v22",
) -> list[tuple[ExtractedImage, int]]:
    """Extract images directly from DOCX word/media/ via python-docx.

    Returns list of (ExtractedImage, paragraph_index) tuples.
    paragraph_index is used later for page mapping.
    """
    from docx import Document
    from docx.oxml.ns import qn

    os.makedirs(output_dir, exist_ok=True)
    doc = Document(docx_path)
    results: list[tuple[ExtractedImage, int]] = []
    seq = 0

    for para_idx, para in enumerate(doc.paragraphs):
        drawings = para._element.findall('.//' + qn('w:drawing'))
        if not drawings:
            continue

        for drawing in drawings:
            # Find the blip element which contains the image reference
            blips = drawing.findall('.//' + qn('a:blip'))
            if not blips:
                continue

            for blip in blips:
                embed_id = blip.get(qn('r:embed'))
                if not embed_id:
                    continue

                try:
                    rel = doc.part.rels[embed_id]
                    image_blob = rel.target_part.blob
                    content_type = rel.target_part.content_type
                except (KeyError, AttributeError):
                    continue

                if not image_blob:
                    continue

                # Determine format
                ext = "png"
                if "jpeg" in content_type or "jpg" in content_type:
                    ext = "jpg"
                elif "gif" in content_type:
                    ext = "gif"
                elif "bmp" in content_type:
                    ext = "bmp"

                # Get dimensions
                try:
                    img = Image.open(io.BytesIO(image_blob))
                    width, height = img.size
                except Exception:
                    width, height = 0, 0

                if width < _MIN_DOCX_IMAGE_SIZE or height < _MIN_DOCX_IMAGE_SIZE:
                    continue

                # Convert to PNG for consistency
                png_bytes = image_blob
                if ext != "png":
                    try:
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        png_bytes = buf.getvalue()
                        ext = "png"
                    except Exception:
                        pass

                seq += 1
                checksum = hashlib.sha256(png_bytes).hexdigest()
                filename = f"{prefix}_d{seq}.{ext}"
                filepath = os.path.join(output_dir, filename)

                with open(filepath, "wb") as f:
                    f.write(png_bytes)

                results.append((
                    ExtractedImage(
                        file_path=filepath,
                        page_number=0,  # filled in later by page mapping
                        sequence=seq,
                        width=width,
                        height=height,
                        format=ext,
                        file_size=len(png_bytes),
                        checksum=checksum,
                        source="docx",
                    ),
                    para_idx,
                ))

    logger.info("[EXTRACTOR] Extracted %d images from DOCX: %s", len(results), docx_path)
    return results


def extract_page_images(
    page: fitz.Page,
    page_number: int,
    output_dir: str,
    prefix: str,
    doc: fitz.Document,
) -> list[ExtractedImage]:
    """Extract images from a single page.

    Tries embedded extraction first. If no meaningful images are found,
    falls back to full-page render at high DPI.
    """
    os.makedirs(output_dir, exist_ok=True)
    results: list[ExtractedImage] = []

    image_list = page.get_images(full=True)
    seq = 0

    for img_info in image_list:
        xref = img_info[0]
        try:
            pix = fitz.Pixmap(doc, xref)
        except Exception:
            continue

        if pix.width < _MIN_EMBEDDED_SIZE or pix.height < _MIN_EMBEDDED_SIZE:
            continue

        if pix.n > 4:
            pix = fitz.Pixmap(fitz.csRGB, pix)

        seq += 1
        ext = "png"
        filename = f"{prefix}_p{page_number}_i{seq}.{ext}"
        filepath = os.path.join(output_dir, filename)

        img_bytes = pix.tobytes("png")
        checksum = hashlib.sha256(img_bytes).hexdigest()

        with open(filepath, "wb") as f:
            f.write(img_bytes)

        results.append(ExtractedImage(
            file_path=filepath,
            page_number=page_number,
            sequence=seq,
            width=pix.width,
            height=pix.height,
            format=ext,
            file_size=len(img_bytes),
            checksum=checksum,
            source="embedded",
        ))

    if not results:
        # Only render full page if it's NOT a text-heavy page (likely a diagram/table)
        page_text = page.get_text().strip()
        if len(page_text) < 500:
            results = _render_full_page(page, page_number, output_dir, prefix, seq)
        else:
            logger.debug("[EXTRACTOR] Skipping full-page render for text-heavy page %d (%d chars)", page_number, len(page_text))

    return results


def _render_full_page(
    page: fitz.Page,
    page_number: int,
    output_dir: str,
    prefix: str,
    seq_offset: int,
) -> list[ExtractedImage]:
    """Render the entire page as a high-resolution image."""
    pix = page.get_pixmap(dpi=_RENDER_DPI)
    seq = seq_offset + 1
    filename = f"{prefix}_p{page_number}_full.png"
    filepath = os.path.join(output_dir, filename)

    img_bytes = pix.tobytes("png")
    checksum = hashlib.sha256(img_bytes).hexdigest()

    with open(filepath, "wb") as f:
        f.write(img_bytes)

    return [ExtractedImage(
        file_path=filepath,
        page_number=page_number,
        sequence=seq,
        width=pix.width,
        height=pix.height,
        format="png",
        file_size=len(img_bytes),
        checksum=checksum,
        source="fullpage",
    )]
