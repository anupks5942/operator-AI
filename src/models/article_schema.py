"""
Canonical Article Schema for the SpyderWash Knowledge Base.

Each KB article is parsed into this structured format during ingestion.
This enables both vector-based retrieval (ChromaDB) and structured/vectorless
retrieval (SQLite) from the same canonical source.
"""
from pydantic import BaseModel, Field


class CanonicalArticle(BaseModel):
    article_id: str = Field(
        ...,
        description="Stable identifier (e.g. KB-PORTAL-001) for citation and linking.",
    )
    status: str = Field(
        default="current",
        description="'current' or 'deprecated'. Only current articles are served to operators.",
    )
    category: str = Field(
        default="",
        description="Normalized category (e.g. 'Account/Login Issue', 'No Connection Error').",
    )
    product: str = Field(
        default="",
        description="Normalized product/device area (e.g. 'Hub', 'POS', 'Legacy Kiosk').",
    )
    device_type: str = Field(
        default="",
        description="Normalized device routing dimension: Hub, POS, Legacy Kiosk, Platinum Kiosk, Card Reader, or General.",
    )
    audience: str = Field(
        default="operator",
        description="Target audience: 'operator' or 'customer'.",
    )
    intent: str = Field(
        default="",
        description="Mapped intent from KB metadata (e.g. 'Another user cannot log in').",
    )
    search_terms: list[str] = Field(
        default_factory=list,
        description="Keywords for retrieval matching.",
    )
    direct_answer: str = Field(
        default="",
        description="The first 1-2 sentence verified explanation (DIRECT ANSWER section).",
    )
    recommended_steps: list[str] = Field(
        default_factory=list,
        description="Ordered troubleshooting steps for reported malfunctions.",
    )
    optional_steps: list[str] = Field(
        default_factory=list,
        description="Informational/configuration steps (not troubleshooting).",
    )
    resolution_criteria: str = Field(
        default="",
        description="Observable result proving the issue is resolved (RESOLUTION CONFIRMED WHEN).",
    )
    escalation_condition: str = Field(
        default="",
        description="When to escalate (ESCALATE WHEN).",
    )
    evidence_to_collect: str = Field(
        default="",
        description="Minimum data to collect after escalation (EVIDENCE TO COLLECT).",
    )
    co_retrieval_ids: list[str] = Field(
        default_factory=list,
        description="Companion article IDs that must be co-retrieved.",
    )
    example_phrases: list[str] = Field(
        default_factory=list,
        description="Example customer/operator phrases that map to this article.",
    )
    raw_body: str = Field(
        default="",
        description="Full article body text (for vector embedding). Internal KB references stripped.",
    )
