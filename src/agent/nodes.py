import re
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

# Brand keywords recognised in user queries → Qdrant metadata filter values
_BRAND_FILTER_MAP = {
    "speed queen": "Speed Queen",
    "speedqueen":  "Speed Queen",
    "maytag":      "Maytag",
    "huebsch":     "Huebsch",
    "alliance":    "Alliance",
    "spyderwash":  "SpyderWash",
    "setomatic":   "SpyderWash",
}

# Router intent → v2.2 article category mapping for metadata-boosted retrieval.
_INTENT_TO_CATEGORY_MAP = {
    "machine_down": "Machines Not Working",
    "machines_not_starting": "Machines Not Working",
    "emergency_store_down": "Entire Store Down",
    "multiple_machines_offline": "No Connection Error",
    "kiosk_not_responding": "Kiosk Troubleshooting",
    "refund_request": "Refund Request",
    "loyalty_balance": "Loyalty Card Balance",
    "transaction_lookup": "Transaction Lookup",
}

# Query text → device_type hint for Hybrid retrieval filtering.
_DEVICE_HINT_MAP = [
    ("legacy kiosk", "Legacy Kiosk"),
    ("platinum kiosk", "Platinum Kiosk"),
    ("card reader", "Card Reader"),
    ("washer", "Card Reader"),
    ("dryer", "Card Reader"),
    ("kiosk", "Kiosk"),
    ("hub", "Hub"),
    ("pos", "POS"),
    ("portal", "Portal"),
]


def _infer_device_type(state: AgentState) -> str:
    """Best-effort device routing hint from entities or query text."""
    entities: dict = state.get("extracted_entities") or {}
    device = entities.get("device_type") or entities.get("device") or entities.get("product")
    if device:
        return str(device)

    messages = state.get("messages", [])
    latest_text = messages[-1].content.lower() if messages else ""
    for keyword, canonical in _DEVICE_HINT_MAP:
        if keyword in latest_text:
            return canonical
    return ""


def _extract_metadata_filter(state: AgentState) -> dict | None:
    """
    Build an optional Qdrant metadata filter from the router's extracted_entities
    and the raw user message.

    Priority:
      1. If extracted_entities specifies a target article_id, use it directly.
      2. If extracted_entities contains a 'brand' key, use it.
      3. Otherwise scan the latest message for known brand keywords.
      4. If a doc_type hint or intent-to-category mapping exists, layer it in.
      5. Always prefer primary-source articles over bible supplements.

    Returns a metadata filter dict or None if no filter applies.
    """
    entities: dict = state.get("extracted_entities") or {}
    messages = state.get("messages", [])
    latest_text = messages[-1].content.lower() if messages else ""
    current_intent = state.get("current_intent") or ""

    filters = {}

    target_article = entities.get("article_id")
    if target_article:
        return {"article_id": {"$eq": target_article}}

    brand = entities.get("brand")
    if not brand:
        for keyword, canonical in _BRAND_FILTER_MAP.items():
            if keyword in latest_text:
                brand = canonical
                break

    if brand:
        filters["brand"] = {"$eq": brand}

    if _is_product_overview_query(latest_text):
        filters["doc_type"] = {"$eq": "overview"}

    doc_type = entities.get("doc_type")
    if doc_type:
        filters["doc_type"] = {"$eq": doc_type}

    category = _INTENT_TO_CATEGORY_MAP.get(current_intent)
    if category and "doc_type" not in filters:
        filters["category"] = {"$eq": category}

    if not filters:
        return None

    if len(filters) == 1:
        return filters
    return {"$and": [{k: v} for k, v in filters.items()]}


_TROUBLESHOOT_MARKERS = (
    "recommended steps",
    "resolution confirmed when",
    "resolution is confirmed when",
    "escalate when",
    "if the issue persists",
    "if the issue remains",
    "if the issue remains unresolved",
    "if you have completed all the above steps",
    "if you are still unable",
    "please follow these steps",
    "please follow these recommended",
    "follow these steps",
    "follow these recommended",
    "try logging in",
    "power-cycle",
    "restart the",
    "contact spyderwash support",
    "reach out to spyderwash support",
    "reset your password",
    "reset password",
    "clear your browser",
    "try a different browser",
    "check credentials",
    "double-check",
    "ensure caps lock",
    "incognito",
)


def _answer_contains_troubleshooting(answer: str) -> bool:
    """Detect troubleshooting content in a RAG answer regardless of intent."""
    lower = answer.lower()
    return sum(1 for m in _TROUBLESHOOT_MARKERS if m in lower) >= 2


_TROUBLESHOOT_INTENTS = {
    "technical_support", "kiosk_not_responding", "machines_not_starting",
    "machine_down", "multiple_machines_offline", "refund_request",
}


_FOLLOWUP_WORDS = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please",
    "provide", "go", "show", "tell", "give", "more", "details",
    "info", "steps", "those", "the", "me", "it", "ahead",
})

_FOLLOWUP_PHRASES = (
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please",
    "provide", "show me", "tell me", "give me", "go ahead",
    "more details", "more info", "the steps", "those steps",
    "yes please", "yes provide", "provide me",
)

_KB_ARTICLE_PATTERN = re.compile(r"KB-[A-Z]+-\d+")


def _get_prior_ai_content(messages) -> str | None:
    """Walk backwards past the latest human message to find the prior AI reply."""
    for msg in reversed(messages[:-1]):
        if msg.type == "ai" and msg.content and str(msg.content).strip():
            return msg.content
    return None


def _is_short_followup(text: str) -> bool:
    """True when the message is a short affirmative/request follow-up (<=6 words)."""
    words = text.strip().lower().split()
    if len(words) > 6 or len(words) == 0:
        return False
    lower = text.strip().lower().rstrip(".,!?")
    if any(lower == p or lower.startswith(p + " ") or lower.endswith(" " + p) for p in _FOLLOWUP_PHRASES):
        return True
    return bool(set(words) & _FOLLOWUP_WORDS) and len(words) <= 4


def _expand_followup_query(messages) -> tuple[str, dict | None]:
    """
    If the latest message is a short follow-up, expand the query using context
    from the prior AI message.

    Returns (query, article_filter_or_None).
    - Strategy 1: If prior AI references a KB article, return expanded query +
      article_id metadata filter for precise retrieval.
    - Strategy 2: If no article IDs but prior AI exists, prepend its first
      sentence for topic signal.
    - Otherwise: return original message unchanged.
    """
    latest = messages[-1].content
    if not _is_short_followup(latest):
        return latest, None

    prior_ai = _get_prior_ai_content(messages)
    if not prior_ai:
        return latest, None

    if "did this resolve" in prior_ai.lower():
        return latest, None

    article_ids = _KB_ARTICLE_PATTERN.findall(prior_ai)
    if article_ids:
        target_id = article_ids[-1]
        expanded = f"{prior_ai[:200]} {latest}"
        return expanded, {"article_id": {"$eq": target_id}}

    first_sentence = prior_ai.split(".")[0].strip()
    if first_sentence:
        return f"{first_sentence}. {latest}", None

    return latest, None


def retrieve_and_generate(state: AgentState):
    """
    RAG_Node: retrieves relevant chunks from Qdrant (Hybrid by default) with optional
    metadata filtering, recursive co-retrieval, and ordered step context.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"messages": [AIMessage(content="I could not find any messages to process. Please try again.")]}

    latest_message = messages[-1].content

    expanded_query, followup_filter = _expand_followup_query(messages)

    metadata_filter = _extract_metadata_filter(state)
    if followup_filter:
        metadata_filter = followup_filter

    rag_service = get_rag_service()
    current_intent = state.get("current_intent") or ""
    device_type = _infer_device_type(state)
    response = rag_service.query(
        expanded_query,
        channel=state.get("channel", "chat"),
        metadata_filter=metadata_filter,
        intent=current_intent,
        device_type=device_type,
    )
    answer = response.get("answer", "I'm sorry, I couldn't find an answer to your question.")

    current_intent = state.get("current_intent") or ""
    answer_lower = answer.lower()
    has_content_markers = _answer_contains_troubleshooting(answer)
    has_any_marker = any(m in answer_lower for m in _TROUBLESHOOT_MARKERS)
    should_prompt = (
        has_content_markers
        or (current_intent in _TROUBLESHOOT_INTENTS and has_any_marker)
    )

    _TRAILING_QUESTION_PHRASES = (
        "would you like me to",
        "do you want me to",
        "shall i provide",
        "would you like to see",
        "want me to walk you through",
    )
    has_trailing_question = any(p in answer_lower for p in _TRAILING_QUESTION_PHRASES)

    if should_prompt and not has_trailing_question:
        answer += "\n\nDid this resolve the issue? (Yes/No)"
        return {
            "messages": [AIMessage(content=answer)],
            "extracted_entities": {"troubleshooting_done": True},
        }

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
    return {
        "messages": [AIMessage(content=msg)],
        "escalation_dispatched": None,
        "troubleshooting_failed": None,
        "blast_radius": None,
        "extracted_entities": {
            "troubleshooting_done": False,
            "blast_radius_asked": False,
            "escalation_confirmation_asked": False,
        },
    }


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
    "IMPORTANT: If a [SYSTEM NOTE] at the end lists active escalation ticket IDs, you MUST "
    "include ALL of them in the Tickets / refunds section. Do not omit any ticket ID.\n\n"
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

    all_tickets = state.get("all_session_tickets") or []
    open_tickets = set(state.get("dispatched_tickets") or [])
    if all_tickets:
        lines = []
        for tid in all_tickets:
            status = "OPEN" if tid in open_tickets else "RESOLVED"
            lines.append(f"- {tid} ({status})")
        transcript += f"\n\n[SYSTEM NOTE — All escalation tickets this session:\n" + "\n".join(lines) + "]"

    llm = create_chat_model(temperature=0)
    response = llm.invoke([
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        HumanMessage(content=f"Conversation to summarise:\n\n{transcript}"),
    ])
    summary = response.content if getattr(response, "content", None) else (
        "I couldn't generate a summary right now. Please try again."
    )
    return {"messages": [AIMessage(content=summary)]}