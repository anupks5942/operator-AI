"""GPT-4o vision captioning with SHA256 cache.

Generates captions and visual summaries for extracted KB images.
Uses image_caption_cache table so re-runs are free.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import sqlite3
from dataclasses import dataclass

from src.services.images.extractor import ExtractedImage

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o"
_MAX_CONCURRENCY = 3


@dataclass
class CaptionResult:
    checksum: str
    caption: str
    visual_summary: str
    image_type: str


def caption_images(
    images: list[ExtractedImage],
    db_path: str,
    model: str | None = None,
    max_concurrency: int | None = None,
) -> dict[str, CaptionResult]:
    """Caption a batch of images. Returns {checksum: CaptionResult}.

    Checks cache first; only calls GPT-4o for uncached checksums.
    """
    from src.config import _env_str
    caption_model = model or _env_str("IMAGE_CAPTION_MODEL", _DEFAULT_MODEL)
    concurrency = max_concurrency or int(_env_str("IMAGE_CAPTION_MAX_CONCURRENCY", str(_MAX_CONCURRENCY)))

    cached = _load_cache(db_path, [img.checksum for img in images])
    uncached = [img for img in images if img.checksum not in cached]

    results: dict[str, CaptionResult] = dict(cached)

    if uncached:
        logger.info("[CAPTIONER] %d cached, %d need GPT-4o captioning", len(cached), len(uncached))
        new_results = asyncio.run(_caption_batch(uncached, caption_model, concurrency))
        _save_cache(db_path, new_results, caption_model)
        results.update(new_results)
    else:
        logger.info("[CAPTIONER] All %d images served from cache", len(cached))

    return results


def _load_cache(db_path: str, checksums: list[str]) -> dict[str, CaptionResult]:
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    results: dict[str, CaptionResult] = {}
    try:
        for cs in checksums:
            row = conn.execute(
                "SELECT caption, visual_summary FROM image_caption_cache WHERE checksum = ?",
                (cs,),
            ).fetchone()
            if row:
                results[cs] = CaptionResult(
                    checksum=cs,
                    caption=row["caption"],
                    visual_summary=row["visual_summary"],
                    image_type=_infer_type_from_summary(row["visual_summary"]),
                )
    finally:
        conn.close()
    return results


def _save_cache(db_path: str, results: dict[str, CaptionResult], model: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for cs, r in results.items():
            conn.execute(
                """INSERT OR REPLACE INTO image_caption_cache
                   (checksum, caption, visual_summary, model) VALUES (?, ?, ?, ?)""",
                (cs, r.caption, r.visual_summary, model),
            )
        conn.commit()
    finally:
        conn.close()


async def _caption_batch(
    images: list[ExtractedImage],
    model: str,
    concurrency: int,
) -> dict[str, CaptionResult]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    semaphore = asyncio.Semaphore(concurrency)
    results: dict[str, CaptionResult] = {}

    async def _process(img: ExtractedImage):
        async with semaphore:
            result = await _caption_single(client, img, model)
            if result:
                results[img.checksum] = result

    tasks = [_process(img) for img in images]
    await asyncio.gather(*tasks)
    return results


async def _caption_single(client, img: ExtractedImage, model: str) -> CaptionResult | None:
    try:
        with open(img.file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        response = await client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "You are analyzing a screenshot/diagram from a laundromat equipment manual. "
                        "Respond with exactly three lines:\n"
                        "CAPTION: <one-line description of what this image shows>\n"
                        "SUMMARY: <visible buttons, fields, labels, error messages, arrows, device states>\n"
                        "TYPE: <one of: screenshot, diagram, table, photo, warning, ui_instruction>"
                    )},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}},
                ],
            }],
            max_tokens=300,
            temperature=0,
        )

        text = response.choices[0].message.content or ""
        caption = ""
        summary = ""
        img_type = "screenshot"

        for line in text.strip().split("\n"):
            if line.startswith("CAPTION:"):
                caption = line[8:].strip()
            elif line.startswith("SUMMARY:"):
                summary = line[8:].strip()
            elif line.startswith("TYPE:"):
                img_type = line[5:].strip().lower()

        return CaptionResult(
            checksum=img.checksum,
            caption=caption or "Untitled image",
            visual_summary=summary,
            image_type=img_type,
        )
    except Exception as exc:
        logger.warning("[CAPTIONER] Failed to caption %s: %s", img.file_path, exc)
        return CaptionResult(
            checksum=img.checksum,
            caption="Image (captioning failed)",
            visual_summary="",
            image_type="screenshot",
        )


def _infer_type_from_summary(summary: str) -> str:
    lower = summary.lower()
    if "table" in lower:
        return "table"
    if "diagram" in lower or "wiring" in lower:
        return "diagram"
    if "warning" in lower or "caution" in lower:
        return "warning"
    if "photo" in lower or "device" in lower:
        return "photo"
    return "screenshot"
