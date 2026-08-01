"""
Article body parser for v2.2 Knowledge Base articles.

Parses raw article body text into structured CanonicalArticle fields:
direct_answer, recommended_steps, optional_steps, resolution_criteria,
escalation_condition, evidence_to_collect.

Also strips internal KB-XXX references so they never reach the operator.
"""
import re
from src.models.article_schema import CanonicalArticle
from src.services.metadata_normalizer import (
    normalize_category,
    normalize_device,
    extract_device_type_from_product,
)


_METADATA_PATTERN = re.compile(
    r"METADATA:\s*category=([^;]+);\s*product=([^;]+);\s*audience=([^;]+);\s*intent=([^;]+);\s*search_terms=(.+)",
    re.IGNORECASE,
)

_CO_RETRIEVAL_PATTERN = re.compile(
    r"CO-RETRIEVAL RULE:?\s*(.+?)(?:\n|$)", re.IGNORECASE
)

_ARTICLE_ID_REF_PATTERN = re.compile(r"KB-[A-Z]+-\d+")

_EXAMPLE_PHRASES_PATTERN = re.compile(
    r"EXAMPLE (?:CUSTOMER|OPERATOR) PHRASES?:\s*(.+?)(?:\n|$)", re.IGNORECASE
)

_SECTION_PATTERNS = {
    "direct_answer": re.compile(
        r"DIRECT ANSWER:?\s*(.+?)(?=\n(?:RECOMMENDED STEPS|OPTIONAL STEPS|RESOLUTION|ESCALATE|EVIDENCE|CO-RETRIEVAL|$))",
        re.DOTALL | re.IGNORECASE,
    ),
    "recommended_steps": re.compile(
        r"RECOMMENDED STEPS?\s*\n(.+?)(?=\n(?:OPTIONAL STEPS|RESOLUTION|ESCALATE|EVIDENCE|CO-RETRIEVAL|$))",
        re.DOTALL | re.IGNORECASE,
    ),
    "optional_steps": re.compile(
        r"OPTIONAL STEPS?\s*\n(.+?)(?=\n(?:RESOLUTION|ESCALATE|EVIDENCE|CO-RETRIEVAL|$))",
        re.DOTALL | re.IGNORECASE,
    ),
    "resolution": re.compile(
        r"RESOLUTION CONFIRMED WHEN:?\s*(.+?)(?=\n(?:ESCALATE|EVIDENCE|CO-RETRIEVAL|$))",
        re.DOTALL | re.IGNORECASE,
    ),
    "escalation": re.compile(
        r"ESCALATE WHEN:?\s*(.+?)(?=\n(?:EVIDENCE|CO-RETRIEVAL|$))",
        re.DOTALL | re.IGNORECASE,
    ),
    "evidence": re.compile(
        r"EVIDENCE TO COLLECT:?\s*(.+?)(?=\n(?:CO-RETRIEVAL|$))",
        re.DOTALL | re.IGNORECASE,
    ),
}

_STEP_PATTERN = re.compile(r"^\s*(\d+)\.\s+(.+)", re.MULTILINE)

_KB_REFERENCE_PATTERN = re.compile(
    r",?\s*(?:refer to|see|retrieve|use)\s+KB-[A-Z]+-\d+[^.]*\.?\s*",
    re.IGNORECASE,
)

_KB_INLINE_REF_PATTERN = re.compile(
    r"\s*\(?\s*(?:see|refer to|retrieve)\s+KB-[A-Z]+-\d+\s*\)?\s*",
    re.IGNORECASE,
)


def _extract_steps(text: str) -> list[str]:
    """Extract numbered steps from a section."""
    steps = []
    matches = _STEP_PATTERN.findall(text)
    if matches:
        for _, step_text in matches:
            cleaned = step_text.strip()
            cleaned = _strip_kb_references(cleaned)
            if cleaned:
                steps.append(cleaned)
    return steps


def _strip_kb_references(text: str) -> str:
    """Remove internal KB-XXX-XXX references from text that would confuse operators."""
    text = _KB_REFERENCE_PATTERN.sub("", text)
    text = _KB_INLINE_REF_PATTERN.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def parse_article_body(article_id: str, body: str) -> CanonicalArticle:
    """
    Parse a raw v2.2 article body into a structured CanonicalArticle.

    Args:
        article_id: The KB article ID (e.g. "KB-PORTAL-001")
        body: The raw text between ARTICLE START and ARTICLE END markers.

    Returns:
        A fully populated CanonicalArticle instance.
    """
    # Extract metadata
    category = ""
    product = ""
    audience = "operator"
    intent = ""
    search_terms: list[str] = []

    meta_match = _METADATA_PATTERN.search(body)
    if meta_match:
        category = meta_match.group(1).strip()
        product = meta_match.group(2).strip()
        audience = meta_match.group(3).strip().lower()
        intent = meta_match.group(4).strip()
        raw_terms = meta_match.group(5).strip()
        search_terms = [t.strip() for t in raw_terms.split(",") if t.strip()]
        if not search_terms:
            search_terms = [t.strip() for t in raw_terms.split() if t.strip()]

    # Status
    status = "current"
    if "DEPRECATED" in body[:300].upper() or "SUPERSEDED" in body[:300].upper():
        status = "deprecated"

    # Co-retrieval IDs
    co_retrieval_ids: list[str] = []
    co_match = _CO_RETRIEVAL_PATTERN.search(body)
    if co_match:
        found_ids = _ARTICLE_ID_REF_PATTERN.findall(co_match.group(1))
        co_retrieval_ids = [cid for cid in found_ids if cid != article_id]

    # Example phrases
    example_phrases: list[str] = []
    phrase_match = _EXAMPLE_PHRASES_PATTERN.search(body)
    if phrase_match:
        raw_phrases = phrase_match.group(1).strip()
        example_phrases = [p.strip() for p in raw_phrases.split("|") if p.strip()]

    # Extract structured sections
    direct_answer = ""
    da_match = _SECTION_PATTERNS["direct_answer"].search(body)
    if da_match:
        direct_answer = _strip_kb_references(da_match.group(1).strip())

    recommended_steps: list[str] = []
    rs_match = _SECTION_PATTERNS["recommended_steps"].search(body)
    if rs_match:
        recommended_steps = _extract_steps(rs_match.group(1))

    optional_steps: list[str] = []
    os_match = _SECTION_PATTERNS["optional_steps"].search(body)
    if os_match:
        optional_steps = _extract_steps(os_match.group(1))

    resolution_criteria = ""
    res_match = _SECTION_PATTERNS["resolution"].search(body)
    if res_match:
        resolution_criteria = _strip_kb_references(res_match.group(1).strip())

    escalation_condition = ""
    esc_match = _SECTION_PATTERNS["escalation"].search(body)
    if esc_match:
        escalation_condition = _strip_kb_references(esc_match.group(1).strip())

    evidence_to_collect = ""
    ev_match = _SECTION_PATTERNS["evidence"].search(body)
    if ev_match:
        evidence_to_collect = _strip_kb_references(ev_match.group(1).strip())

    # Build clean body for vector embedding (stripped of internal references)
    raw_body = _strip_kb_references(body)

    # Normalize metadata
    normalized_category = normalize_category(category)
    normalized_product = normalize_device(product)
    device_type = extract_device_type_from_product(product)

    return CanonicalArticle(
        article_id=article_id,
        status=status,
        category=normalized_category,
        product=normalized_product,
        device_type=device_type,
        audience=audience,
        intent=intent,
        search_terms=search_terms,
        direct_answer=direct_answer,
        recommended_steps=recommended_steps,
        optional_steps=optional_steps,
        resolution_criteria=resolution_criteria,
        escalation_condition=escalation_condition,
        evidence_to_collect=evidence_to_collect,
        co_retrieval_ids=co_retrieval_ids,
        example_phrases=example_phrases,
        raw_body=raw_body,
    )
