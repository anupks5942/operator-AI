import uuid
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage, ToolMessage
from src.agent.state import AgentState
from src.agent.nodes import (
    retrieve_and_generate,
    guardrail_node,
    pci_guardrail_node,
    handle_out_of_domain,
    handle_greeting,
    workflow_reminder_node,
    summarize_conversation_node,
    _extract_metadata_filter,
)
from src.agent.router import semantic_router, infer_blast_radius
from src.agent.tools import SETOMATIC_TOOLS
from src.services.notifications import NotificationService
from src.services.rag_service import RAGService
from src.utils.security import mask_credit_cards, sanitize_outbound_text
from src.llm import create_chat_model

# Hardware/outage intents that must follow Gregg's multi-turn workflow:
# blast-radius question → KB troubleshooting → confirmation → escalation (if failed).
_ESCALATION_WORKFLOW_INTENTS = frozenset({
    "emergency_store_down",
    "machine_down",
    "escalation_request",
    "machines_not_starting",
    "multiple_machines_offline",
})

# Short operator replies that must not be used as the RAG search query.
_BLAST_RADIUS_REPLY_PHRASES = frozenset({
    "entire location", "one machine", "yes", "no", "it did not",
    "still down", "entire laundromat offline", "just one", "specific machine",
    "just one machine", "yes, that fixed it", "yes that fixed it",
})


def _is_conversational_workflow_reply(text: str) -> bool:
    """Return True when the message is a blast-radius or yes/no workflow answer."""
    normalized = text.strip().lower().rstrip(".")
    if normalized in _BLAST_RADIUS_REPLY_PHRASES:
        return True
    if len(normalized) <= 30 and any(
        token in normalized
        for token in ("one machine", "just one", "entire", "whole store", "all machines")
    ):
        return True
    if normalized.startswith(("yes", "no", "nope", "nah")) and len(normalized) <= 20:
        return True
    return False


def _extract_escalation_context(messages) -> str:
    """Build ticket summary from the current incident only (not earlier resolved issues)."""
    trivial = frozenset({"no", "yes", "nope", "nah", "wait yes", "wait, yes"})
    boundary_markers = (
        "glad to hear the issue is resolved",
        "critical escalation ticket",
        "no problem. if you need further assistance, you can reach the support team directly",
    )
    start_after = 0
    for i, msg in enumerate(messages):
        if msg.type == "ai" and msg.content:
            lower = msg.content.lower()
            if any(marker in lower for marker in boundary_markers):
                start_after = i + 1

    human_texts = [
        m.content.strip() for m in messages[start_after:] if m.type == "human"
    ]
    substantive = [
        text for text in human_texts
        if text.lower().rstrip(".,") not in trivial and len(text) > 3
    ]
    if not substantive:
        fallback = human_texts[-1] if human_texts else "Unknown issue"
        return sanitize_outbound_text(fallback)
    if len(substantive) >= 2:
        summary = f"{substantive[-2]} | Latest update: {substantive[-1]}"
    else:
        summary = substantive[-1]
    return sanitize_outbound_text(summary)


_ESCALATION_SUMMARY_PROMPT = """You are generating a concise technical handoff summary for an on-call technician.
Given the conversation between an operator and the AI support agent, produce a structured summary.

RULES:
- Be factual and concise. No filler language.
- Only include fields where information is available in the conversation.
- The "Steps Attempted" should list what troubleshooting the agent recommended.
- The "Outcome" should state what the operator reported after trying those steps.

OUTPUT FORMAT (plain text, no markdown):
ISSUE: [1-2 sentence description of the problem]
EQUIPMENT: [Machine type, ID, position, location if mentioned — or "Not specified"]
STEPS ATTEMPTED: [Bullet list of troubleshooting steps offered]
OUTCOME: [What the operator reported — still down, didn't work, etc.]
SEVERITY: [Critical (entire location offline) OR Standard (single/few machines)]
"""


def _generate_escalation_summary(messages, blast_radius: str | None = None) -> str:
    """Use LLM to generate a structured technical handoff summary from the conversation."""
    import logging
    _logger = logging.getLogger("setomatic.escalation")

    boundary_markers = (
        "glad to hear the issue is resolved",
        "critical escalation ticket",
        "no problem. if you need further assistance, you can reach the support team directly",
    )
    start_after = 0
    for i, msg in enumerate(messages):
        if msg.type == "ai" and msg.content:
            lower = msg.content.lower()
            if any(marker in lower for marker in boundary_markers):
                start_after = i + 1

    relevant_messages = messages[start_after:]
    conversation_text = []
    for msg in relevant_messages:
        if not msg.content or not str(msg.content).strip():
            continue
        role = "Operator" if msg.type == "human" else "Agent"
        conversation_text.append(f"{role}: {msg.content.strip()}")

    if not conversation_text:
        return "ISSUE: Unknown issue\nEQUIPMENT: Not specified\nSTEPS ATTEMPTED: None\nOUTCOME: Unknown\nSEVERITY: Standard"

    severity_hint = "Critical (entire location offline)" if blast_radius == "entire_location" else "Standard (single/few machines)"
    user_input = (
        f"CONVERSATION:\n" + "\n".join(conversation_text[-20:]) +
        f"\n\nSEVERITY CONTEXT: {severity_hint}"
    )

    try:
        llm = create_chat_model(temperature=0)
        response = llm.invoke([
            {"role": "system", "content": _ESCALATION_SUMMARY_PROMPT},
            {"role": "user", "content": user_input},
        ])
        summary = response.content.strip()
        if summary:
            return sanitize_outbound_text(summary)
    except Exception as exc:
        _logger.warning("LLM escalation summary failed, falling back to heuristic: %s", exc)

    return sanitize_outbound_text(_extract_escalation_context(messages))


def _get_prior_assistant_content(messages) -> str | None:
    for msg in reversed(messages[:-1]):
        if msg.type == "ai" and msg.content:
            return msg.content
    return None


def _user_indicates_resolved(text: str) -> bool:
    lower = text.lower()
    return any(
        marker in lower
        for marker in (
            "resolved", "fixed it", "fixed", "all good", "working now", "now working",
            "working fine", "working again", "back up", "back online", "back to normal",
            "up and running", "issue is fixed", "problem solved",
        )
    )


def _format_conversation_for_email(messages) -> str:
    """Format the full session transcript for the escalation email body."""
    lines: list[str] = []
    for msg in messages:
        if not msg.content or not str(msg.content).strip():
            continue
        text = mask_credit_cards(str(msg.content).strip())
        if msg.type == "human":
            lines.append(f"Operator: {text}")
        elif msg.type == "ai":
            lines.append(f"Agent: {text}")
    return "\n\n".join(lines) if lines else "No conversation history available."


def _resolve_operator_contact(state: AgentState) -> tuple[str, str, str]:
    entities = state.get("extracted_entities") or {}
    operator_id = state.get("operator_id")

    name = (
        state.get("operator_name")
        or entities.get("operator_name")
        or (f"Operator #{operator_id}" if operator_id is not None else "Unknown Operator")
    )
    email = state.get("operator_email") or entities.get("operator_email") or "unknown@operator.local"
    phone = state.get("operator_phone") or entities.get("operator_phone") or "N/A"
    return str(name), str(email), str(phone)

# ── Inline node definitions ───────────────────────────────────────────────────

def escalation_node(state: AgentState):
    """
    Triggered when troubleshooting fails after a store-down or hardware outage workflow.
    Generates an LLM-based professional technical summary and dispatches via email + SMS.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"messages": [AIMessage(content="Escalation failed: No conversation context found.")]}

    blast_radius = state.get("blast_radius") or (state.get("extracted_entities") or {}).get("blast_radius")
    structured_summary = _generate_escalation_summary(messages, blast_radius=blast_radius)
    conversation = _format_conversation_for_email(messages)
    name, email, phone = _resolve_operator_contact(state)
    ticket_number = f"TKT-{uuid.uuid4().hex[:8].upper()}"

    NotificationService.send_escalation(
        ticket_id=ticket_number,
        name=name,
        email=email,
        phone=phone,
        conversation=conversation,
        summary=structured_summary,
    )

    short_issue = structured_summary.split("\n")[0].replace("ISSUE: ", "") if structured_summary else "Unknown issue"
    response_content = (
        f'A critical escalation ticket ({ticket_number}) has been created and dispatched '
        f'to the on-call technician. They will contact you shortly regarding: "{short_issue}"'
    )
    return {
        "messages": [AIMessage(content=response_content)],
        "escalation_dispatched": True,
        "extracted_entities": {
            "troubleshooting_done": True,
            "blast_radius_asked": False,
            "escalation_confirmation_asked": False,
            "escalation_ticket_id": ticket_number,
        },
    }


def new_issue_after_escalation_node(state: AgentState):
    """Resets all workflow state from the previous escalation cycle.

    If the user's message already implies a clear blast radius (e.g. 'Machine 5 is down'
    or 'everything is offline'), skip the blast-radius question entirely — the conditional
    edge after this node will chain directly to troubleshoot_first or escalation_node.
    """
    messages = state.get("messages", [])
    user_text = messages[-1].content if messages and messages[-1].type == "human" else ""
    blast_radius = infer_blast_radius(user_text)

    base_entities = {
        "troubleshooting_done": False,
        "troubleshooting_failed": False,
        "blast_radius": None,
        "escalation_confirmation_asked": False,
    }

    result = {
        "extracted_entities": base_entities,
        "blast_radius": blast_radius,
        "escalation_required": True,
        "troubleshooting_failed": None,
        "escalation_dispatched": None,
    }

    if blast_radius:
        base_entities["blast_radius_asked"] = False
    else:
        msg = AIMessage(content="To help me get you the right fix, is this affecting just one specific machine, or is your entire laundromat offline?")
        base_entities["blast_radius_asked"] = True
        result["messages"] = [msg]

    return result


def _route_after_new_issue(state: AgentState) -> str:
    """Conditional edge after new_issue_after_escalation: chain to next node or end."""
    blast_radius = state.get("blast_radius")
    if not blast_radius:
        return "__end__"
    if blast_radius == "entire_location":
        return "escalation"
    return "troubleshoot_first"


def blast_radius_check_node(state: AgentState):
    # Ask the operator if the downtime affects a single machine or the entire location to decide RAG vs escalation.
    msg = AIMessage(content="To help me get you the right fix, is this affecting just one specific machine, or is your entire laundromat offline?")
    return {
        "messages": [msg],
        "extracted_entities": {
            "blast_radius_asked": True,
            "troubleshooting_done": False,
            "troubleshooting_failed": False,
        },
    }


def clarify_issue_node(state: AgentState):
    """Asks for more detail when the issue description is too vague to produce useful troubleshooting."""
    msg = AIMessage(content=(
        "I understand there's an issue with your machine. Could you provide more details? "
        "For example:\n"
        "- Is it not starting?\n"
        "- Is it showing an error message or code?\n"
        "- Is it making unusual sounds?\n"
        "- Is the display blank or frozen?\n\n"
        "This will help me give you the right troubleshooting steps."
    ))
    return {
        "messages": [msg],
        "extracted_entities": {"clarify_asked": True},
    }


def troubleshoot_first_node(state: AgentState):
    # Route location-wide system outage reports to retrieve troubleshooting manuals.
    messages = state.get("messages", [])

    # Walk backwards through messages to find the original hardware issue, skipping short
    # conversational replies (blast-radius answers, yes/no) that would pollute the RAG query.
    query = "system outage troubleshooting"
    for msg in reversed(messages):
        if msg.type == "human":
            content = msg.content.strip()
            if len(content) > 5 and not _is_conversational_workflow_reply(content):
                query = content
                break

    entities = dict(state.get("extracted_entities") or {})
    intent = state.get("current_intent") or ""
    # Read blast_radius from top-level state first, fall back to extracted_entities for compatibility.
    blast_radius = state.get("blast_radius") or entities.get("blast_radius", "entire_location")
    blast_radius_str = str(blast_radius).replace("_", " ")

    is_entire_location = (
        str(blast_radius) in ("entire_location", "entire location")
        or intent in ("emergency_store_down", "multiple_machines_offline")
    )
    if is_entire_location and not entities.get("doc_type"):
        entities["doc_type"] = "troubleshooting_guide"
    if intent in ("machines_not_starting", "machine_down", "kiosk_not_responding") and not entities.get("doc_type"):
        entities["doc_type"] = "troubleshooting_guide"

    # Bias location-wide outages toward hub/gateway/network KB chunks, not single-machine power steps.
    if is_entire_location:
        combined_query = (
            f"hub bluetooth gateway internet network connectivity system outage "
            f"troubleshooting {query} affecting {blast_radius_str}"
        )
    else:
        combined_query = f"{query} affecting {blast_radius_str}"

    metadata_filter = _extract_metadata_filter({**state, "extracted_entities": entities})
    rag_service = RAGService()
    response = rag_service.query(combined_query, metadata_filter=metadata_filter)
    answer = response.get("answer", "Please verify local network connections and power cycle your devices.")

    context_docs = response.get("context", [])
    if context_docs:
        source_tags = sorted({
            f"{doc.metadata.get('source_file', 'Unknown')} [p.{doc.metadata.get('page', '?')}]"
            for doc in context_docs
        })
        sources_note = "\n\n**Sources:** " + " | ".join(source_tags)
        answer += sources_note

    # Explicitly concatenate the resolution prompt so the router detects the next turn as a confirmation.
    full_response = answer + "\n\nDid this resolve the issue? (Yes/No)"

    entities["troubleshooting_done"] = True

    return {
        "messages":          [AIMessage(content=full_response)],
        "extracted_entities": entities,
        # Persist blast_radius to top-level state so subsequent turns can read it without dict lookup.
        "blast_radius":       blast_radius,
    }


def escalation_resolved_node(state: AgentState):
    # Route to resolution response since initial troubleshooting resolved the system issue.
    # Reset all workflow flags so subsequent messages are treated as fresh conversations
    # rather than being trapped in the completed workflow's state.

    # If an escalation ticket was dispatched, notify the team that the issue is now resolved.
    if state.get("escalation_dispatched"):
        entities = state.get("extracted_entities") or {}
        ticket_id = entities.get("escalation_ticket_id", "")
        issue_context = _extract_escalation_context(state.get("messages", []))
        NotificationService.send_resolution(ticket_id=ticket_id, issue_summary=issue_context)

    msg = AIMessage(content="Glad to hear the issue is resolved! Let me know if there is anything else I can help you with.")
    return {
        "messages": [msg],
        "extracted_entities": {
            "troubleshooting_done": False,
            "troubleshooting_failed": False,
            "blast_radius": None,
            "blast_radius_asked": False,
            "clarify_asked": False,
            "escalation_ticket_id": None,
        },
        "blast_radius": None,
        "escalation_required": None,
        "troubleshooting_failed": None,
        "escalation_dispatched": None,
    }


def confirm_escalation_node(state: AgentState):
    """Asks the operator whether they want the issue escalated (single-machine failures only)."""
    msg = AIMessage(content=(
        "I wasn't able to resolve this with the troubleshooting steps available. "
        "Would you like me to escalate this to the on-call technician, or would you "
        "prefer to contact support directly at Support@setomaticsystems.com / (516) 990-4055?"
    ))
    return {
        "messages": [msg],
        "extracted_entities": {"escalation_confirmation_asked": True},
    }


def escalation_declined_node(state: AgentState):
    """Provides direct support contact info when operator declines escalation."""
    msg = AIMessage(content=(
        "No problem. If you need further assistance, you can reach the support team directly:\n\n"
        "- Email: Support@setomaticsystems.com\n"
        "- Phone: (516) 990-4055\n\n"
        "Let me know if there's anything else I can help you with."
    ))
    return {
        "messages": [msg],
        "extracted_entities": {
            "troubleshooting_done": False,
            "escalation_confirmation_asked": False,
            "blast_radius_asked": False,
        },
        "blast_radius": None,
        "troubleshooting_failed": None,
    }


def post_escalation_ack_node(state: AgentState):
    # After a ticket is dispatched, avoid restarting the outage workflow on follow-up noise.
    msg = AIMessage(content=(
        "Your escalation ticket has already been dispatched to the on-call technician, "
        "and they will follow up with you shortly. If the issue is resolved before they "
        "reach out, no further action is needed."
    ))
    return {"messages": [msg]}


_TOOL_SYSTEM_PROMPT = (
    "You are a Setomatic/SpyderWash technical support agent with access to tools. "
    "Use the tools available to you to answer the user's question accurately.\n\n"

    "CRITICAL OUTAGE RULE: If the user reports a system outage OR asks whether SpyderWash or Setomatic "
    "is down, you MUST call the check_global_system_status tool FIRST before doing anything else. "
    "After receiving the tool result, follow these rules EXACTLY:\n\n"
    "1. If the result says '[Setomatic Systems] STATUS: No Issue' or similar 'No Issue'/'Operational': "
    "tell the user the global system is fully operational. Their issue is a LOCAL network problem. "
    "Provide these hub troubleshooting steps:\n"
    "   a. Power-cycle the SpyderWash Hub (unplug for 30 seconds, replug).\n"
    "   b. Verify the hub's Ethernet cable is firmly seated on both the hub and the router.\n"
    "   c. Confirm the router has internet access (open a browser on a connected device).\n"
    "   d. Check the hub's LED — solid green = connected; flashing amber = no internet.\n"
    "   e. If amber, reboot the router/modem and wait 5 minutes.\n"
    "   f. If still failing, contact Setomatic support at Support@setomaticsystems.com or (516) 990-4055.\n\n"
    "2. If the result contains 'HISTORICAL INCIDENT': the tool only has stale backup data. "
    "Tell the user: 'I checked our backup status source but the data is from a past incident that "
    "has likely been resolved. The current Setomatic status page shows no active outages. "
    "Please verify at https://setomaticsystems.com/status.' Then provide the local troubleshooting steps above.\n\n"
    "3. If the result says 'STATUS: Degraded' or contains an active outage event with a recent date: "
    "confirm the global outage and advise the user to monitor https://setomaticsystems.com/status. "
    "No local troubleshooting is needed until the global issue is resolved.\n\n"
    "4. If the result says 'SYSTEM STATUS CHECK FAILED': tell the user you could not automatically "
    "check the status page and ask them to visit https://setomaticsystems.com/status directly.\n\n"

    "DATE RANGE RULE: When calling get_transaction_history, if the operator specifies a date range "
    "(e.g. 'transactions from March', 'last week', 'between Jan 1 and Jan 15'), pass start_date and "
    "end_date in YYYY-MM-DD format. If no dates are mentioned, omit them — the tool defaults to a "
    "rolling 6-month window. ALWAYS prefer the operator's explicit dates over the default.\n\n"

    "CRITICAL REFUND RULE: If the user asks for a refund on any transaction, you MUST follow this "
    "exact 3-step sequential workflow. Do NOT skip or reorder any step:\n\n"
    "  STEP 1 — Call get_transaction_history with the user's loyalty card number to retrieve recent "
    "transactions. If the operator specified a date range, include start_date and end_date. "
    "Each transaction line includes its ID in the format [ID:xxxx]. Identify the "
    "transactionDetailId for the transaction the user wants refunded. If the user has not provided "
    "a card number, ask for it before proceeding.\n\n"
    "  STEP 2 — Call check_refund_eligibility with that transactionDetailId. Parse the result:\n"
    "    - If the result says 'IS eligible': inform the user and proceed to Step 3.\n"
    "    - If the result says 'is NOT eligible': inform the user of the reason and STOP. "
    "Do NOT call execute_refund under any circumstances if eligibility is false.\n\n"
    "  STEP 3 — ONLY if Step 2 confirmed eligibility: call execute_refund with the same "
    "transactionDetailId. Report the refund confirmation message and receipt number "
    "(e.g. REF-998877) back to the user."
)

_tool_llm = None

def _get_tool_llm():
    global _tool_llm
    if _tool_llm is None:
        _tool_llm = create_chat_model(temperature=0).bind_tools(SETOMATIC_TOOLS)
    return _tool_llm

def tool_node(state: AgentState):
    """
    Tool_Node: Executes tools via a ReAct-style loop until the LLM produces
    a plain-text response (no more tool_calls).

    WHY A LOOP: The refund workflow requires sequential tool calls:
      get_transaction_history → check_refund_eligibility → execute_refund
    A single-shot implementation (invoke → tool → summarize) causes the
    "summarize" LLM call to itself return tool_calls=[...] for the next step.
    That AIMessage gets persisted to state WITHOUT a ToolMessage response,
    causing OpenAI 400 errors on subsequent turns.

    The loop guarantees that every AIMessage with tool_calls is ALWAYS
    followed by its ToolMessages before the next LLM call — maintaining a
    valid OpenAI message sequence at all times.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"messages": [AIMessage(content="No query to process.")]}

    tool_map      = {t.name: t for t in SETOMATIC_TOOLS}
    llm_with_tools = _get_tool_llm()

    # ── Build entity hint from router state ───────────────────────────────────
    entities   = state.get("extracted_entities") or {}
    intent     = state.get("current_intent") or ""
    hint_parts = []

    if intent:
        hint_parts.append(f"Active workflow intent: {intent}.")
    if entities:
        entity_lines = "\n".join(
            f"  - {k}: {v}" for k, v in entities.items() if v is not None
        )
        hint_parts.append(
            "The router has already extracted the following entities from the "
            "user's input. Use them directly as tool arguments — do NOT ask the "
            f"user for them again:\n{entity_lines}"
        )

    base_system = {"role": "system", "content": _TOOL_SYSTEM_PROMPT}
    msgs        = [base_system]
    if hint_parts:
        msgs.append({
            "role":    "system",
            "content": "EXTRACTED CONTEXT (use immediately):\n" + "\n".join(hint_parts),
        })
    msgs += list(messages)

    # ── ReAct loop ────────────────────────────────────────────────────────────
    # `new_messages` collects everything added THIS invocation (appended to state).
    # `msgs`         is the growing working context sent to the LLM each round.
    new_messages   = []
    MAX_ITERATIONS = 6   # safety cap — prevents runaway tool chains

    for _ in range(MAX_ITERATIONS):
        ai_response = llm_with_tools.invoke(msgs)

        # Always accumulate the AI response
        new_messages.append(ai_response)
        msgs.append(ai_response)

        # If the LLM produced text (no tool calls), we are done
        if not ai_response.tool_calls:
            break

        # Execute every tool call; always add a ToolMessage (even on failure)
        # so the message sequence is ALWAYS valid for OpenAI
        for tool_call in ai_response.tool_calls:
            tool_fn = tool_map.get(tool_call["name"])
            if tool_fn:
                try:
                    result = tool_fn.invoke(tool_call["args"])
                except Exception as exc:
                    result = f"Tool '{tool_call['name']}' raised an error: {exc}"
            else:
                result = (
                    f"Unknown tool '{tool_call['name']}'. "
                    f"Available tools: {list(tool_map.keys())}"
                )

            tool_msg = ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
            new_messages.append(tool_msg)
            msgs.append(tool_msg)

    # When a tool action runs, the user has switched context (e.g., from outage
    # troubleshooting to checking balance/transactions). Clear workflow flags to
    # prevent stale state from leaking into unrelated future interactions.
    return {
        "messages": new_messages,
        "extracted_entities": {
            "troubleshooting_done": False,
            "blast_radius_asked": False,
        },
        "blast_radius": None,
        "troubleshooting_failed": None,
        "escalation_dispatched": None,
    }



# ── Conditional routing ───────────────────────────────────────────────────────

def route_after_classifier(state: AgentState) -> str:
    """
    Priority-ordered conditional routing after the Intent Classifier.
    """
    intent = state.get("current_intent", "")

    # PCI: CVV / track data — static refusal, no LLM or external APIs.
    if intent == "pci_sensitive_data":
        return "pci_guardrail"

    # Conversation summary: honored at any point, even mid-workflow, so the operator
    # can recap the chat without breaking or losing the active workflow state.
    if intent == "conversation_summary":
        return "summarize"

    # Escalation confirmation gate: handle operator's yes/no response to "Would you like me to escalate?"
    entities = state.get("extracted_entities") or {}
    messages = state.get("messages", [])
    _last_text = messages[-1].content.strip().lower() if messages else ""

    if entities.get("escalation_confirmation_asked") and not state.get("escalation_dispatched"):
        _confirm_positive = {"yes", "yeah", "yep", "yup", "ya", "yaa", "y", "si", "sí", "sure", "please", "ok", "okay"}
        _confirm_negative = {"no", "nope", "nah", "n", "cancel", "nevermind"}
        _confirm_phrases_yes = ("yes please", "go ahead", "escalate", "please escalate", "do it")
        _confirm_phrases_no = ("no thanks", "i'll call", "ill call", "contact them myself", "no need", "no,", "no.")
        # Strip punctuation from words for reliable matching (e.g., "no," → "no")
        _cleaned_words = {w.rstrip(".,!?;:") for w in _last_text.split()}
        if (
            _cleaned_words & _confirm_positive
            or any(phrase in _last_text for phrase in _confirm_phrases_yes)
        ):
            return "escalation"
        if (
            _cleaned_words & _confirm_negative
            or any(phrase in _last_text for phrase in _confirm_phrases_no)
        ):
            return "escalation_declined"
        return "confirm_escalation"

    # Mid-workflow interruption guard: if the outage workflow is active (troubleshooting_done
    # or blast_radius_asked) and the user sends gibberish/greeting/off-topic, re-prompt.
    # But NOT after escalation is dispatched — that means the workflow completed.
    # Positive-word passthrough: "yes"/"yaa" should only pass through during the
    # troubleshooting_done phase (answering "Did this resolve?"), NOT during blast_radius_asked
    # where "yes" is ambiguous and doesn't answer "one machine or entire laundromat?".

    if intent in ("out_of_domain", "greeting") and (
        entities.get("troubleshooting_done") or entities.get("blast_radius_asked")
    ) and not state.get("escalation_dispatched"):
        _quick_positive = {"yes", "yeah", "yep", "yup", "ya", "yaa", "yah", "y", "si", "sí"}
        if entities.get("troubleshooting_done") and (
            _last_text in _quick_positive or _last_text.split()[0:1] == ["yes"]
        ):
            pass  # Fall through to the outage workflow block where positive-word check runs
        else:
            return "workflow_reminder"

    # Secondary gibberish guard: when troubleshooting_done is active and the user's message
    # is very short (≤5 chars) with no recognizable English words, the LLM may misclassify
    # gibberish as technical_support/general_query instead of out_of_domain. Catch it here.
    if entities.get("troubleshooting_done") and not state.get("escalation_dispatched"):
        _quick_positive = {"yes", "yeah", "yep", "yup", "ya", "yaa", "yah", "y", "si", "sí"}
        _quick_negative = {"no", "nope", "nah"}
        if (
            len(_last_text) <= 6
            and _last_text not in _quick_positive
            and _last_text not in _quick_negative
            and not _last_text.isdigit()
        ):
            return "workflow_reminder"

    # Greeting: friendly response without RAG or LLM call.
    if intent == "greeting":
        return "greeting"

    # Out-of-domain and prompt injection: route directly to the static refusal node.
    if intent == "out_of_domain":
        return "out_of_domain"

    # Hard block: live hardware status requests are refused by the guardrail node.
    if state.get("hardware_lookup_attempted"):
        return "guardrail"

    messages = state.get("messages", [])
    prior_ai = _get_prior_assistant_content(messages)
    if prior_ai and any(
        marker in prior_ai.lower()
        for marker in ("critical escalation ticket", "already been dispatched")
    ):
        latest = messages[-1].content if messages else ""
        if _user_indicates_resolved(latest):
            return "escalation_resolved"
        # Allow API-action intents (balance, transactions, refund, status) to proceed
        # normally — operators shouldn't be trapped after escalation for unrelated actions.
        if state.get("api_action_required"):
            return "tool"
        # Allow new issue reports to start a fresh cycle instead of trapping them.
        if intent in _ESCALATION_WORKFLOW_INTENTS and len(latest.split()) >= 3:
            return "new_issue_after_escalation"
        return "post_escalation_ack"

    # Post-resolution closure: after "Glad to hear..." if the user replies with a simple
    # negative/closure ("no", "no thanks", "I'm good"), treat it as conversation end.
    if prior_ai and "glad to hear the issue is resolved" in prior_ai.lower():
        latest = messages[-1].content.strip().lower() if messages else ""
        _closure_words = {"no", "nope", "nah", "nothing", "bye", "thanks", "thank", "gracias", "adios"}
        _closure_phrases = (
            "no thanks", "no thank", "i'm good", "im good", "that's all",
            "thats all", "nothing else", "all good", "bye", "thank you",
        )
        if (
            set(latest.split()) & _closure_words
            or any(phrase in latest for phrase in _closure_phrases)
        ) and len(latest.split()) <= 5:
            return "greeting"

    # Critical outage is a confirmed production failure — skip troubleshooting and dispatch immediately.
    # But respect the deduplication guard: don't re-escalate if already dispatched.
    if intent == "critical_outage":
        if state.get("escalation_dispatched"):
            return "post_escalation_ack"
        return "escalation"

    # Multi-turn outage workflow: confirm blast radius, troubleshoot, then escalate only on failure.
    if intent in _ESCALATION_WORKFLOW_INTENTS or state.get("escalation_required"):
        entities = state.get("extracted_entities") or {}
        messages = state.get("messages", [])

        # When the blast-radius question was already asked, ONLY trust the heuristic —
        # the LLM/router promotes blast_radius to top-level state which may be hallucinated.
        if entities.get("blast_radius_asked") and not entities.get("troubleshooting_done"):
            blast_radius = None
            if messages and messages[-1].type == "human":
                blast_radius = infer_blast_radius(messages[-1].content)
            if not blast_radius:
                return "blast_radius_check"
        else:
            # Read blast_radius from top-level state first, then fall back to extracted_entities.
            blast_radius = state.get("blast_radius") or entities.get("blast_radius")
            if not blast_radius and messages and messages[-1].type == "human":
                blast_radius = infer_blast_radius(messages[-1].content)

        # Pause and ask scope before any KB retrieval when blast radius is still unknown.
        if not blast_radius and not entities.get("troubleshooting_done"):
            return "blast_radius_check"

        # Entire location offline = critical situation — escalate immediately, no troubleshooting.
        if blast_radius == "entire_location" and not entities.get("troubleshooting_done"):
            if state.get("escalation_dispatched"):
                return "post_escalation_ack"
            return "escalation"

        # Single/few machines: retrieve troubleshooting documentation before any escalation.
        # But first check if the issue description is too vague to produce useful results.
        if not entities.get("troubleshooting_done"):
            # Only ask for clarification ONCE — if already asked, proceed to troubleshoot.
            if not entities.get("clarify_asked"):
                _issue_action_words = {
                    "down", "offline", "broken", "error", "frozen", "stuck", "starting",
                    "not", "won't", "wont", "dead", "blank", "beeping", "flashing",
                    "noise", "sound", "leaking", "stopped", "responding", "working",
                    "light", "blinking", "green", "amber", "red", "display",
                }
                _best_issue_msg = ""
                for msg in reversed(messages):
                    if msg.type == "human":
                        content = msg.content.strip()
                        if len(content) > 5 and not _is_conversational_workflow_reply(content):
                            _best_issue_msg = content.lower()
                            break
                if not (set(_best_issue_msg.split()) & _issue_action_words) and len(_best_issue_msg.split()) <= 3:
                    return "clarify_issue"
            return "troubleshoot_first"

        # Negative language sets used for both LLM-extracted and heuristic escalation checks.
        messages = state.get("messages", [])
        user_text = messages[-1].content.lower() if messages else ""
        user_words = set(user_text.split())

        # Detect new issue descriptions that contain "down"/"offline" but are NOT a
        # negative confirmation. E.g., "one machine is down" is a new report, not "no".
        _machine_terms = {"machine", "washer", "dryer", "kiosk", "hub", "unit"}
        _is_new_issue_description = (
            len(user_words) >= 4
            and bool(user_words & _machine_terms)
        )
        if _is_new_issue_description:
            _inferred = infer_blast_radius(user_text)
            if _inferred == "entire_location":
                return "escalation"
            if _inferred == "single_machine":
                return "troubleshoot_first"
            return "blast_radius_check"

        _negative_words = {
            "no", "nope", "nah", "not", "still", "broken", "failed",
            "offline", "unresolved", "didn't", "didnt", "doesn't", "doesnt",
            "down", "worse", "nothing", "same",
        }
        _negative_phrases = (
            "not resolved", "not working", "still down", "didn't work",
            "did not work", "same issue", "same problem", "not fixed",
            "still broken", "no luck", "doesn't work", "does not work",
            "still not", "no funciona", "sigue sin",
        )
        _has_negative = (
            bool(user_words & _negative_words)
            or any(phrase in user_text for phrase in _negative_phrases)
        )

        # Positive override: if the message contains strong resolution indicators,
        # treat it as confirmation even if it also has a negative word (e.g., "issue resolved").
        _positive_override_words = {"resolved", "fixed", "working", "sorted", "solved", "done"}
        _positive_override_phrases = ("issue resolved", "problem fixed", "working now", "all good", "issue is fixed")
        _has_positive_override = (
            bool(user_words & _positive_override_words)
            or any(phrase in user_text for phrase in _positive_override_phrases)
        )
        if _has_positive_override and not any(neg in user_text for neg in ("not resolved", "not fixed", "not working")):
            return "escalation_resolved"

        # Question-structure guard: messages phrased as questions (re-stating symptoms)
        # should not trigger escalation. E.g., "Is it not starting?" is not "no".
        _is_question = (
            user_text.rstrip().endswith("?")
            or user_text.startswith(("is ", "does ", "can ", "will ", "has ", "are ", "do "))
        )
        if _has_negative and _is_question and len(user_words) >= 4:
            return "workflow_reminder"

        # Deduplication guard: if a ticket was already dispatched in this session,
        # do NOT create another one — route to the acknowledgment node instead.
        if state.get("escalation_dispatched"):
            if _has_negative:
                return "post_escalation_ack"
            return "workflow_reminder"

        # Route to escalation when the router extracted troubleshooting_failed —
        # but ONLY if the user's message actually contains recognizable negative language.
        # Gibberish classified as failure by the LLM must not auto-escalate.
        # Tiered: entire_location auto-escalates; single_machine asks for confirmation first.
        if state.get("troubleshooting_failed") is True or entities.get("troubleshooting_failed") is True:
            if _has_negative:
                if blast_radius == "entire_location":
                    return "escalation"
                return "confirm_escalation"
            return "workflow_reminder"

        # Heuristic: treat negative confirmation language as escalation after KB steps were offered.
        if entities.get("troubleshooting_done") and _has_negative:
            if blast_radius == "entire_location":
                return "escalation"
            return "confirm_escalation"

        # Route to the resolved node ONLY when the user explicitly confirms resolution.
        # Gibberish or ambiguous replies must not be treated as positive confirmation.
        if state.get("troubleshooting_failed") is False or entities.get("troubleshooting_failed") is False:
            messages = state.get("messages", [])
            user_text = messages[-1].content.lower() if messages else ""
            user_words = set(user_text.split())
            _positive_words = {
                "yes", "yeah", "yep", "yup", "ya", "yaa", "yah", "y", "si", "sí",
                "fixed", "resolved", "working", "works", "good", "great",
                "done", "solved", "correct", "okay", "ok", "sure", "absolutely",
            }
            _positive_phrases = (
                "that fixed", "it worked", "all good", "working now",
                "issue is fixed", "resolved it", "that worked", "problem solved",
                "yes it did", "it's working", "its working", "fixed it",
            )
            if user_words & _positive_words or any(phrase in user_text for phrase in _positive_phrases):
                return "escalation_resolved"
            # Ambiguous or gibberish reply — re-prompt for a clear Yes/No.
            return "workflow_reminder"

    # API workflows: loyalty balance, transaction lookup, refund, system status check.
    if state.get("api_action_required"):
        return "tool"

    # All remaining intents (general_query, technical_support, etc.) go to RAG.
    return "rag"



def route_after_rag(state: AgentState) -> str:
    # Only escalate after RAG if we're in an active troubleshooting workflow where the
    # prior AI asked "Did this resolve?" — NOT for general RAG queries that happen to
    # contain words like "not" or "down" (e.g., "light not blinking", "machine is down").
    entities = state.get("extracted_entities") or {}
    if not entities.get("troubleshooting_done"):
        return "__end__"

    messages = state.get("messages", [])
    last_human_text = ""
    for msg in reversed(messages):
        if msg.type == "human":
            last_human_text = msg.content.lower()
            break

    user_words = set(last_human_text.split())
    _negative_words = {"no", "nope", "nah", "not", "still", "broken", "failed", "offline", "down", "unresolved", "didn't", "didnt", "doesn't", "doesnt"}
    if user_words & _negative_words:
        blast_radius = state.get("blast_radius") or entities.get("blast_radius")
        if blast_radius == "entire_location":
            return "escalation"
        return "confirm_escalation"
    return "__end__"


# ── Graph compilation ─────────────────────────────────────────────────────────

def create_agent_graph():
    """
    Compiles and returns the LangGraph state graph with MemorySaver checkpointing.
    Each conversation thread is identified by a 'thread_id' in the run config,
    allowing multi-turn state persistence across separate .invoke() / .stream() calls.
    """
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("router",            semantic_router)
    workflow.add_node("guardrail_node",    guardrail_node)
    workflow.add_node("pci_guardrail_node", pci_guardrail_node)
    workflow.add_node("escalation_node",   escalation_node)
    workflow.add_node("tool_node",         tool_node)
    workflow.add_node("rag_agent",         retrieve_and_generate)
    # Static refusal node: no LLM, no API — hardcoded response for off-topic or adversarial input.
    workflow.add_node("out_of_domain_node", handle_out_of_domain)
    # Greeting node: friendly response for simple greetings.
    workflow.add_node("greeting_node", handle_greeting)
    # Workflow reminder: re-prompts when user sends gibberish mid-outage-workflow.
    workflow.add_node("workflow_reminder_node", workflow_reminder_node)
    # Summary node: recaps the conversation on demand ("summarise this chat").
    workflow.add_node("summarize_node", summarize_conversation_node)
    # Register the multi-turn conversational escalation guardrail nodes.
    workflow.add_node("blast_radius_check",  blast_radius_check_node)
    workflow.add_node("clarify_issue",       clarify_issue_node)
    workflow.add_node("troubleshoot_first",  troubleshoot_first_node)
    workflow.add_node("escalation_resolved", escalation_resolved_node)
    workflow.add_node("post_escalation_ack", post_escalation_ack_node)
    # Tiered escalation: asks single-machine operators to confirm before dispatching.
    workflow.add_node("confirm_escalation", confirm_escalation_node)
    workflow.add_node("escalation_declined", escalation_declined_node)
    # Fresh-cycle node: resets state from a completed escalation and starts new outage workflow.
    workflow.add_node("new_issue_after_escalation", new_issue_after_escalation_node)

    # Entry point
    workflow.set_entry_point("router")

    # Multi-turn conditional routing after intent classification.
    workflow.add_conditional_edges(
        "router",
        route_after_classifier,
        {
            "greeting":             "greeting_node",
            "summarize":            "summarize_node",
            "workflow_reminder":     "workflow_reminder_node",
            "out_of_domain":        "out_of_domain_node",
            "pci_guardrail":        "pci_guardrail_node",
            "guardrail":            "guardrail_node",
            "escalation":           "escalation_node",
            "tool":                 "tool_node",
            "rag":                  "rag_agent",
            "blast_radius_check":   "blast_radius_check",
            "troubleshoot_first":   "troubleshoot_first",
            "clarify_issue":        "clarify_issue",
            "escalation_resolved":  "escalation_resolved",
            "post_escalation_ack":  "post_escalation_ack",
            "confirm_escalation":   "confirm_escalation",
            "escalation_declined":  "escalation_declined",
            "new_issue_after_escalation": "new_issue_after_escalation",
        }
    )

    # After the standard RAG node, evaluate whether the user's reply needs escalation.
    workflow.add_conditional_edges(
        "rag_agent",
        route_after_rag,
        {
            "escalation":         "escalation_node",
            "confirm_escalation": "confirm_escalation",
            "__end__":            END,
        }
    )

    # Terminal edges
    workflow.add_edge("greeting_node",          END)
    workflow.add_edge("summarize_node",          END)
    workflow.add_edge("workflow_reminder_node",  END)
    workflow.add_edge("out_of_domain_node",     END)
    workflow.add_edge("pci_guardrail_node", END)
    workflow.add_edge("guardrail_node",     END)
    workflow.add_edge("escalation_node",    END)
    workflow.add_edge("tool_node",          END)
    workflow.add_edge("blast_radius_check",  END)
    workflow.add_edge("clarify_issue",       END)
    workflow.add_edge("troubleshoot_first",  END)
    workflow.add_edge("escalation_resolved", END)
    workflow.add_edge("post_escalation_ack", END)
    workflow.add_edge("confirm_escalation",  END)
    workflow.add_edge("escalation_declined", END)
    workflow.add_conditional_edges(
        "new_issue_after_escalation",
        _route_after_new_issue,
        {
            "__end__":            END,
            "escalation":         "escalation_node",
            "troubleshoot_first": "troubleshoot_first",
        }
    )

    # Attach in-memory checkpointer for multi-turn persistence
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


# Compiled instance (shared across the FastAPI app lifetime)
agent_app = create_agent_graph()
