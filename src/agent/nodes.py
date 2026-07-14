from langchain_core.messages import AIMessage, HumanMessage
from src.agent.state import AgentState
from src.agent.router import _is_product_overview_query
from src.services.rag_service import RAGService
from src.llm import create_chat_model

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

    # Product-overview questions (what is SpyderWash, components, features) retrieve better
    # from overview docs than from large operator manuals.
    if _is_product_overview_query(latest_text):
        filters["doc_type"] = {"$eq": "overview"}

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
        # Return a safe fallback so downstream conditional edges never see an empty message list.
        return {"messages": [AIMessage(content="I could not find any messages to process. Please try again.")]}

    latest_message = messages[-1].content

    # Build per-query metadata filter from state
    metadata_filter = _extract_metadata_filter(state)

    rag_service = get_rag_service()
    response = rag_service.query(latest_message, metadata_filter=metadata_filter)
    answer = response.get("answer", "I'm sorry, I couldn't find an answer to your question.")


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


def pci_guardrail_node(state: AgentState):
    """
    Refuse requests involving CVV, CVC, track data, or other prohibited card auth data.
    PCI-DSS: such data must never be collected, stored, or transmitted.
    """
    refusal_message = (
        "For PCI compliance, I cannot accept or process card verification codes (CVV/CVC), "
        "PIN blocks, or magnetic-stripe/track data. Please do not share this information in chat. "
        "Use the SpyderWash operator portal or official payment channels for payment issues."
    )
    return {"messages": [AIMessage(content=refusal_message)]}


def handle_greeting(state: AgentState):
    """
    Friendly greeting response for simple salutations like 'hi', 'hello', etc.
    Also handles thank-you / goodbye messages with an appropriate acknowledgment
    instead of the full intro greeting.
    No LLM or RAG call — hardcoded to avoid pointless KB lookups on greetings.
    """
    messages = state.get("messages", [])
    user_text = messages[-1].content.strip().lower() if messages else ""

    _thank_words = {"thank", "thanks", "thankyou", "ty", "gracias"}
    _bye_words = {"bye", "goodbye", "adios", "see ya", "later"}
    if any(w in user_text for w in _thank_words):
        msg = "You're welcome! Let me know if there's anything else I can help with."
    elif any(w in user_text for w in _bye_words):
        msg = "Goodbye! Feel free to reach out anytime you need support."
    else:
        msg = (
            "Hello! I'm the SpyderWash technical support agent. "
            "I can help you with machine troubleshooting, loyalty card balances, "
            "transaction history, refunds, and system status checks. "
            "How can I assist you today?"
        )
    return {"messages": [AIMessage(content=msg)]}


def workflow_reminder_node(state: AgentState):
    """
    Re-prompts the user when they send gibberish/off-topic mid-outage-workflow.
    Preserves the active workflow state and gently asks for a Yes/No answer.
    """
    reminder_message = (
        "I didn't quite catch that. We're still working on your reported issue. "
        "Did the troubleshooting steps I provided resolve the problem? Please reply **Yes** or **No**."
    )
    return {"messages": [AIMessage(content=reminder_message)]}


def handle_out_of_domain(state: AgentState):
    """
    Static out-of-domain guardrail: rejects any query unrelated to Setomatic /
    SpyderWash operations, including prompt injection attempts.

    No LLM or API is called — the response is hardcoded to prevent the model
    from being manipulated by adversarial inputs that sneak past the classifier.
    """
    refusal_message = (
        "I am a Setomatic technical support agent. "
        "I can only assist with SpyderWash hardware, portal troubleshooting, and operator actions."
    )
    return {"messages": [AIMessage(content=refusal_message)]}


_SUMMARY_SYSTEM_PROMPT = (
    "You are a Setomatic/SpyderWash support agent. Summarise the support conversation "
    "below for the operator in a clear, friendly recap. Structure the summary as:\n"
    "  - **Issues raised:** what the operator reported\n"
    "  - **Actions taken:** troubleshooting steps provided, lookups performed (balance/transactions), etc.\n"
    "  - **Tickets / refunds:** any escalation tickets dispatched or refunds processed (include IDs if present)\n"
    "  - **Current status:** resolved, escalated, or pending\n\n"
    "Keep it concise and factual. Only include sections that apply. Do NOT invent details "
    "that are not in the conversation. Never include full card numbers or sensitive payment data."
)

# Conversational filler that carries no substantive content for the summary.
_SUMMARY_SKIP_PHRASES = frozenset({
    "summarise", "summarize", "summary", "recap", "tldr", "tl;dr",
})


def summarize_conversation_node(state: AgentState):
    """
    Produces an operator-friendly recap of the conversation so far.

    Reads the full thread history from state (persisted per thread_id), filters to
    substantive human + assistant turns, and asks the LLM to summarise. The current
    "summarise this chat" request itself is excluded from the transcript.
    """
    messages = state.get("messages", [])

    transcript_lines: list[str] = []
    for msg in messages:
        # Only human and assistant messages carry conversational content.
        role = getattr(msg, "type", None)
        content = (getattr(msg, "content", "") or "").strip()
        if not content:
            continue
        if role == "human":
            # Skip the summary request itself so it doesn't pollute the recap.
            if content.strip().lower().rstrip("!.,?") in _SUMMARY_SKIP_PHRASES:
                continue
            transcript_lines.append(f"Operator: {content}")
        elif role == "ai":
            transcript_lines.append(f"Agent: {content}")

    if not transcript_lines:
        return {
            "messages": [AIMessage(content=(
                "There's nothing to summarise yet — we haven't discussed anything in this "
                "conversation so far. How can I help you today?"
            ))]
        }

    transcript = "\n".join(transcript_lines)
    llm = create_chat_model(temperature=0)
    response = llm.invoke([
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        HumanMessage(content=f"Conversation to summarise:\n\n{transcript}"),
    ])
    summary = response.content if getattr(response, "content", None) else (
        "I couldn't generate a summary right now. Please try again."
    )
    return {"messages": [AIMessage(content=summary)]}
