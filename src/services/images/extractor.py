"""Image extraction from PDF pages using PyMuPDF.

Two modes:
  1. Embedded extraction: pull raster images from PDF xref objects.
  2. Full-page render: 200 DPI fallback when embedded images are partial or absent.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_RENDER_DPI = 200
_MIN_EMBEDDED_SIZE = 80  # skip embedded images smaller than 80px on either axis


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
        results = _render_full_page(page, page_number, output_dir, prefix, seq)

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
