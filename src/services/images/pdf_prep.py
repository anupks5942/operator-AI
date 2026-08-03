"""DOCX to PDF conversion. Uses docx2pdf (Word COM) with LibreOffice CLI fallback."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

_GENERATED_DIR = os.path.join("KB", "_generated")


def convert_docx_to_pdf(docx_path: str, output_dir: str | None = None) -> str:
    """Convert a DOCX to PDF. Returns the path to the generated PDF.

    Tries docx2pdf (requires MS Word) first, falls back to LibreOffice CLI.
    """
    if not os.path.isfile(docx_path):
        raise FileNotFoundError(f"DOCX not found: {docx_path}")

    out_dir = output_dir or _GENERATED_DIR
    os.makedirs(out_dir, exist_ok=True)

    basename = os.path.splitext(os.path.basename(docx_path))[0]
    pdf_path = os.path.join(out_dir, f"{basename}.pdf")

    if os.path.exists(pdf_path):
        logger.info("[PDF_PREP] PDF already exists, skipping conversion: %s", pdf_path)
        return pdf_path

    try:
        return _convert_with_docx2pdf(docx_path, pdf_path)
    except Exception as exc:
        logger.warning("[PDF_PREP] docx2pdf failed (%s), trying LibreOffice...", exc)

    return _convert_with_libreoffice(docx_path, out_dir, pdf_path)


def _convert_with_docx2pdf(docx_path: str, pdf_path: str) -> str:
    from docx2pdf import convert
    convert(docx_path, pdf_path)
    if not os.path.exists(pdf_path):
        raise RuntimeError("docx2pdf produced no output")
    logger.info("[PDF_PREP] Converted via docx2pdf: %s", pdf_path)
    return pdf_path


def _convert_with_libreoffice(docx_path: str, out_dir: str, expected_pdf: str) -> str:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise EnvironmentError(
            "Neither MS Word (docx2pdf) nor LibreOffice found. "
            "Install one to convert DOCX to PDF."
        )

    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir, docx_path],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")

    if not os.path.exists(expected_pdf):
        generated = [f for f in os.listdir(out_dir) if f.endswith(".pdf")]
        if generated:
            actual = os.path.join(out_dir, generated[-1])
            os.rename(actual, expected_pdf)

    if not os.path.exists(expected_pdf):
        raise RuntimeError(f"PDF not found after LibreOffice conversion: {expected_pdf}")

    logger.info("[PDF_PREP] Converted via LibreOffice: %s", expected_pdf)
    return expected_pdf
