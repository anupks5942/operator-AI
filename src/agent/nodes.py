from langchain_core.messages import AIMessage
from src.agent.state import AgentState
from src.services.rag_service import RAGService
from src.services.notifications import NotificationService

_rag_service = None

def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service

# Brand keywords recognised in user queries → Chroma metadata filter values
_BRAND_FILTER_MAP = {
    "speed queen": "Speed Queen",
    "speedqueen":  "Speed Queen",
    "maytag":      "Maytag",
    "huebsch":     "Huebsch",
    "alliance":    "Alliance",
    "spyderwash":  "SpyderWash",
    "setomatic":   "SpyderWash",
}

def _extract_metadata_filter(state: AgentState) -> dict | None:
    """
    Build an optional Chroma metadata filter from the router's extracted_entities
    and the raw user message.

    Priority:
      1. If extracted_entities contains a 'brand' key, use it directly.
      2. Otherwise scan the latest message for known brand keywords.
      3. If a doc_type hint exists in extracted_entities, layer that in too.

    Returns a Chroma-compatible filter dict or None if no filter applies.
    """
    entities: dict = state.get("extracted_entities") or {}
    messages = state.get("messages", [])
    latest_text = messages[-1].content.lower() if messages else ""

    filters = {}

    # Brand detection
    brand = entities.get("brand")
    if not brand:
        for keyword, canonical in _BRAND_FILTER_MAP.items():
            if keyword in latest_text:
                brand = canonical
                break

    if brand:
        filters["brand"] = {"$eq": brand}

    # Doc-type hint (e.g. router could set extracted_entities["doc_type"])
    doc_type = entities.get("doc_type")
    if doc_type:
        filters["doc_type"] = {"$eq": doc_type}

    if not filters:
        return None

    # Chroma supports $and for multiple filters
    if len(filters) == 1:
        return filters
    return {"$and": [{k: v} for k, v in filters.items()]}


def retrieve_and_generate(state: AgentState):
    """
    RAG_Node: retrieves relevant chunks from ChromaDB (with optional metadata
    filtering and MMR re-ranking) and generates a grounded answer via Groq LLM.

    Metadata filter logic:
      - If the user mentions a specific brand (e.g. "Speed Queen"), restricts
        vector search to chunks tagged with that brand.
      - If extracted_entities provides a doc_type hint, further narrows the pool.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"messages": []}

    latest_message = messages[-1].content

    # Build per-query metadata filter from state
    metadata_filter = _extract_metadata_filter(state)

    rag_service = get_rag_service()
    response = rag_service.query(latest_message, metadata_filter=metadata_filter)
    answer = response.get("answer", "I'm sorry, I couldn't find an answer to your question.")

    # Surface which sources were used (for transparency)
    context_docs = response.get("context", [])
    if context_docs:
        source_tags = sorted({
            f"{doc.metadata.get('source_file', 'Unknown')} [p.{doc.metadata.get('page', '?')}]"
            for doc in context_docs
        })
        sources_note = "\n\n**Sources:** " + " | ".join(source_tags)
        answer += sources_note

    return {"messages": [AIMessage(content=answer)]}


def guardrail_node(state: AgentState):
    """
    Guardrail node that explicitly refuses hardware status lookups.
    """
    refusal_message = (
        "I'm sorry, but I cannot provide real-time hardware, machine, or port statuses. "
        "Please check the SpyderWash operator portal for live machine status."
    )
    return {"messages": [AIMessage(content=refusal_message)]}
