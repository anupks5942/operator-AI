"""
KB Ingestion Pipeline — parses the v2.2 Knowledge Base document into
structured CanonicalArticles and populates both SQLite (structured) and
SQLite (structured) store. Vector indexing lives in data_injection/.

Usage:
    uv run python -m src.services.kb_ingest

Two-phase structured path:
1. Parse → CanonicalArticle (structured, normalized)
2. Store → SQLite (for Vectorless RAG)
Vector RAG index is built separately: uv run python -m data_injection
"""
import os
import re
import logging
import docx2txt
from src.models.article_schema import CanonicalArticle
from src.services.article_parser import parse_article_body
from src.services.kb_database import initialize_database, upsert_article, upsert_co_retrieval_rules, get_article_count

logger = logging.getLogger(__name__)

_ARTICLE_PATTERN = re.compile(
    r"ARTICLE START:\s*(KB-[A-Z0-9][\w-]*)\s*(.*?)ARTICLE END:\s*\1",
    re.DOTALL,
)

_V22_FILENAME_MARKERS = ("ai_support_knowledge_base", "ai support knowledge base")

_SECTION0_KEEP_HEADERS = {
    "Operator-facing scope and assumptions",
    "Answer selection order",
    "Required customer-response structure",
    "Required Operator-response structure",
    "Question discipline",
    "Security and privacy",
    "RMA and hardware-return control",
    "Financial and contractual accuracy",
    "Software and feature-currentness",
    "Integrated technical content and source priority",
}

_SECTION0_REMOVE_HEADERS = {
    "Primary purpose",
    "Article schema",
    "Recommended RAG ingestion settings",
    "1. Intent Taxonomy and Routing",
    "Technical-reference routing extensions",
    "Fallback questions for Unknown / Ambiguous Issue",
}


def _is_v22_file(filename: str) -> bool:
    name_lower = filename.lower().replace("-", "_").replace(" ", "_")
    return any(marker in name_lower for marker in _V22_FILENAME_MARKERS)


def clean_section0(section0_text: str) -> str:
    """
    Filter Section 0 to keep only operational response rules.
    Removes developer-facing design specs (RAG ingestion settings, article schema, etc.)
    """
    lines = section0_text.split("\n")
    result_lines: list[str] = []
    current_section_keep = True
    in_header_zone = True

    for line in lines:
        stripped = line.strip()

        # Skip the initial title/header block
        if in_header_zone:
            if stripped.startswith("0. AI Retrieval and Response Rules"):
                in_header_zone = False
                continue
            if any(h in stripped for h in (
                "SPYDERWASH", "AI Support Knowledge Base", "Setomatic Systems",
                "Operator-Facing Edition", "Revision 2.",
                "Operator-actionable issue resolution",
            )):
                continue
            if stripped.startswith("Primary purpose"):
                in_header_zone = False
                current_section_keep = False
                continue
            continue

        # Check if this line is a section header
        if stripped and len(stripped) < 80 and not stripped.startswith(("•", "-", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            is_keep_header = any(h in stripped for h in _SECTION0_KEEP_HEADERS)
            is_remove_header = any(h in stripped for h in _SECTION0_REMOVE_HEADERS)

            if is_keep_header:
                current_section_keep = True
                result_lines.append("")
                result_lines.append(stripped)
                continue
            elif is_remove_header:
                current_section_keep = False
                continue

        if current_section_keep and stripped:
            result_lines.append(stripped)

    cleaned = "\n".join(result_lines).strip()
    if len(cleaned) > 5000:
        cleaned = cleaned[:5000]
    return cleaned


def parse_v22_document(file_path: str) -> tuple[list[CanonicalArticle], str]:
    """
    Parse the v2.2 KB document into structured articles and a cleaned Section 0.

    Returns:
        (articles, cleaned_section0_prompt)
    """
    text = docx2txt.process(file_path)

    first_article_idx = text.find("ARTICLE START:")
    if first_article_idx < 0:
        logger.warning("[KB_INGEST] No articles found in %s", file_path)
        return [], ""

    section0_raw = text[:first_article_idx].strip()
    cleaned_section0 = clean_section0(section0_raw)

    articles: list[CanonicalArticle] = []
    for match in _ARTICLE_PATTERN.finditer(text):
        article_id = match.group(1)
        body = match.group(2).strip()

        try:
            article = parse_article_body(article_id, body)
            articles.append(article)
        except Exception as e:
            logger.error("[KB_INGEST] Failed to parse %s: %s", article_id, e)

    logger.info("[KB_INGEST] Parsed %d articles from %s", len(articles), file_path)
    return articles, cleaned_section0


def ingest_to_sqlite(articles: list[CanonicalArticle]):
    """Populate the SQLite KB database with parsed articles."""
    initialize_database()

    for article in articles:
        upsert_article(article)

    # Insert co-retrieval rules after all articles exist (avoids FK failures)
    upsert_co_retrieval_rules(articles)

    count = get_article_count()
    logger.info("[KB_INGEST] SQLite DB now contains %d articles", count)


def find_v22_file(kb_dir: str = "KB") -> str | None:
    """Find the v2.2 KB document in the KB directory."""
    if not os.path.exists(kb_dir):
        return None
    for filename in os.listdir(kb_dir):
        if filename.endswith(".docx") and _is_v22_file(filename):
            return os.path.join(kb_dir, filename)
    return None


def run_full_ingest(kb_dir: str = "KB"):
    """
    Full ingestion pipeline:
    1. Find and parse v2.2 document
    2. Store structured articles in SQLite
    3. Return articles + section0 (vector index via data_injection)
    """
    v22_path = find_v22_file(kb_dir)
    if not v22_path:
        logger.error("[KB_INGEST] No v2.2 KB file found in %s", kb_dir)
        return [], ""

    articles, section0 = parse_v22_document(v22_path)

    if articles:
        ingest_to_sqlite(articles)

    return articles, section0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    articles, section0 = run_full_ingest()
    print(f"\nIngested {len(articles)} articles into SQLite")
    print(f"Cleaned Section 0: {len(section0)} chars")
    if articles:
        sample = articles[0]
        print(f"\nSample article: {sample.article_id}")
        print(f"  Category: {sample.category}")
        print(f"  Device: {sample.device_type}")
        print(f"  Intent: {sample.intent}")
        print(f"  Steps: {len(sample.recommended_steps)}")
        print(f"  Co-retrieval: {sample.co_retrieval_ids}")
