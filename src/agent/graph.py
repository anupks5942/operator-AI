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
from src.agent.router import semantic_router, infer_blast_radius, _is_resolution_message
from src.agent.tools import SETOMATIC_TOOLS
from src.services.notifications import NotificationService
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
        "escalation ticket",
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
- The ISSUE and EQUIPMENT fields must ONLY contain information the OPERATOR explicitly stated.
  Do NOT infer root causes, equipment types, or technical details from the Agent's troubleshooting
  suggestions or knowledge base content. If the operator only said "everything is offline", the
  issue is "everything is offline" — do not add causes the operator never mentioned.
- STEPS ATTEMPTED must ONLY list steps that the AGENT explicitly recommended in the conversation.
  Do NOT infer or invent steps from general knowledge.
- If SEVERITY is Critical (entire location offline) and the agent did NOT offer any troubleshooting
  steps in this incident, set STEPS ATTEMPTED to "None — immediate escalation (entire location offline)".
- The "Outcome" should state what the operator reported after trying those steps.

OUTPUT FORMAT (plain text, no markdown):
ISSUE: [1-2 sentence description of the problem using ONLY the operator's own words]
LOCATION: [Laundromat name, site, or address if the operator mentioned it — or "Not specified"]
EQUIPMENT: [Machine type, ID, or position if the operator mentioned it — or "Not specified"]
STEPS ATTEMPTED: [Bullet list of troubleshooting steps the agent offered, or "None" if immediate escalation]
OUTCOME: [What the operator reported — still down, didn't work, etc.]
SEVERITY: [Critical (entire location offline) OR Standard (single/few machines)]
"""


def _generate_escalation_summary(messages, blast_radius: str | None = None) -> str:
    """Use LLM to generate a structured technical handoff summary from the conversation."""
    import logging
    _logger = logging.getLogger("setomatic.escalation")

    boundary_markers = (
        "glad to hear the issue is resolved",
        "escalation ticket",
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
        content = msg.content.strip()
        if msg.type == "human":
            conversation_text.append(f"Operator: {content}")
        elif msg.type == "ai":
            # Condense long KB/RAG troubleshooting dumps to reduce hallucination
            # of ISSUE/EQUIPMENT, while preserving enough for STEPS ATTEMPTED.
            if len(content) > 300 and content.count("\n") > 3:
                lines = content.split("\n")
                kept: list[str] = []
                for ln in lines:
                    stripped = ln.strip()
                    if not stripped:
                        continue
                    kept.append(stripped)
                    if len(kept) >= 5:
                        break
                condensed = "; ".join(kept)
                conversation_text.append(f"Agent (troubleshooting): {condensed}")
            else:
                conversation_text.append(f"Agent: {content}")

    if not conversation_text:
        return "ISSUE: Unknown issue\nLOCATION: Not specified\nEQUIPMENT: Not specified\nSTEPS ATTEMPTED: None\nOUTCOME: Unknown\nSEVERITY: Standard"

    severity_hint = "Critical (entire location offline)" if blast_radius == "entire_location" else "Standard (single/few machines)"
    troubleshooting_skipped = blast_radius == "entire_location" and not any(
        line.startswith("Agent (troubleshooting):")
        for line in conversation_text
    )
    user_input = (
        f"CONVERSATION:\n" + "\n".join(conversation_text[-20:]) +
        f"\n\nSEVERITY CONTEXT: {severity_hint}" +
        (f"\nNOTE: Troubleshooting was skipped — immediate escalation for entire location." if troubleshooting_skipped else "")
    )

    try:
        llm = create_chat_model(temperature=0)
        response = llm.invoke([
            {"role": "system", "content": _ESCALATION_SUMMARY_PROMPT},
            {"role": "user", "content": user_input},
        ])
        summary = response.content.strip()
        if summary:
            summary = _postprocess_summary(summary, blast_radius)
            return sanitize_outbound_text(summary)
    except Exception as exc:
        _logger.warning("LLM escalation summary failed, falling back to heuristic: %s", exc)

    return sanitize_outbound_text(_extract_escalation_context(messages))


def _postprocess_summary(summary: str, blast_radius: str | None) -> str:
    """Fix LLM summary inconsistencies that the prompt alone can't prevent."""
    lines = summary.split("\n")
    fixed: list[str] = []
    for line in lines:
        upper = line.strip().upper()
        # STEPS: strip "entire location offline" text from non-entire-location tickets.
        if upper.startswith("STEPS ATTEMPTED:") and blast_radius != "entire_location":
            if "entire location" in line.lower():
                line = "STEPS ATTEMPTED: None"
        # SEVERITY: force correct value based on actual blast_radius.
        if upper.startswith("SEVERITY:"):
            if blast_radius == "entire_location":
                line = "SEVERITY: Critical (entire location offline)"
            else:
                line = "SEVERITY: Standard (single/few machines)"
        fixed.append(line)
    return "\n".join(fixed)


def _get_prior_assistant_content(messages) -> str | None:
    for msg in reversed(messages[:-1]):
        if msg.type == "ai" and msg.content:
            return msg.content
    return None


def _user_indicates_resolved(text: str) -> bool:
    return _is_resolution_message(text)


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

    is_critical = blast_radius == "entire_location"
    result = NotificationService.send_escalation(
        ticket_id=ticket_number,
        name=name,
        email=email,
        phone=phone,
        conversation=conversation,
        summary=structured_summary,
        is_critical=is_critical,
    )

    # Accumulate ticket IDs across the session so resolve/summary nodes can reference them.
    existing_tickets = list(state.get("dispatched_tickets") or [])
    existing_tickets.append(ticket_number)

    # Permanent append-only list for summary node (never removed from).
    all_tickets = list(state.get("all_session_tickets") or [])
    all_tickets.append(ticket_number)

    existing_email_ids = dict(state.get("ticket_email_ids") or {})
    if result.message_id:
        existing_email_ids[ticket_number] = result.message_id

    short_issue = structured_summary.split("\n")[0].replace("ISSUE: ", "") if structured_summary else "Unknown issue"
    severity_word = "critical " if is_critical else ""
    response_content = (
        f'A {severity_word}escalation ticket ({ticket_number}) has been created and dispatched '
        f'to the on-call technician. They will contact you shortly regarding: "{short_issue}"'
    )
    return {
        "messages": [AIMessage(content=response_content)],
        "escalation_dispatched": True,
        "dispatched_tickets": existing_tickets,
        "all_session_tickets": all_tickets,
        "ticket_email_ids": existing_email_ids,
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

    # Bias location-wide outages toward hub/gateway/network KB chunks, not single-machine power steps.
    if is_entire_location:
        combined_query = (
            f"hub bluetooth gateway internet network connectivity system outage "
            f"troubleshooting {query} affecting {blast_radius_str}"
        )
    else:
        combined_query = f"{query} affecting {blast_radius_str}"

    metadata_filter = _extract_metadata_filter({**state, "extracted_entities": entities})
    from src.agent.nodes import get_rag_service
    rag_service = get_rag_service()
    response = rag_service.query(combined_query, metadata_filter=metadata_filter)
    answer = response.get("answer", "Please verify local network connections and power cycle your devices.")

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
    """Resolves one or all open escalation tickets. If the user mentions a specific
    ticket ID (TKT-XXXX), resolves that one; if multiple tickets exist and no ID is
    specified, asks the user which one to resolve."""
    import re as _re

    messages = state.get("messages", [])
    dispatched = list(state.get("dispatched_tickets") or [])
    latest_text = messages[-1].content if messages else ""

    ticket_match = _re.search(r"TKT-[A-F0-9]+", latest_text, _re.IGNORECASE)
    resolved_ticket = ticket_match.group(0).upper() if ticket_match else None

    # "all" explicitly resolves every open ticket
    _resolves_all = latest_text.strip().lower() in ("all", "all of them", "all tickets", "resolve all")

    # Multi-ticket disambiguation: ask which ticket to resolve
    if not resolved_ticket and not _resolves_all and len(dispatched) > 1:
        entities = state.get("extracted_entities") or {}
        if not entities.get("ticket_resolution_asked"):
            ticket_list = "\n".join(f"- {tid}" for tid in dispatched)
            msg = AIMessage(content=(
                f"You have {len(dispatched)} open tickets:\n{ticket_list}\n\n"
                "Which ticket is resolved? You can say the ticket number, or 'all' to resolve everything."
            ))
            return {
                "messages": [msg],
                "extracted_entities": {"ticket_resolution_asked": True},
            }

    issue_context = _extract_escalation_context(messages)
    email_ids = state.get("ticket_email_ids") or {}

    if resolved_ticket and resolved_ticket not in dispatched:
        open_list = ", ".join(dispatched) if dispatched else "none"
        msg = AIMessage(content=(
            f"Ticket {resolved_ticket} is not in your open tickets — it may already be resolved. "
            f"Your open tickets are: {open_list}."
        ))
        return {"messages": [msg]}

    if dispatched:
        if resolved_ticket and resolved_ticket in dispatched:
            NotificationService.send_resolution(
                ticket_id=resolved_ticket,
                issue_summary=issue_context,
                original_message_id=email_ids.get(resolved_ticket),
            )
            dispatched.remove(resolved_ticket)
        else:
            for tid in dispatched:
                NotificationService.send_resolution(
                    ticket_id=tid,
                    issue_summary=issue_context,
                    original_message_id=email_ids.get(tid),
                )
            dispatched = []

    still_active = bool(dispatched)

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
            "ticket_resolution_asked": False,
        },
        "blast_radius": None,
        "escalation_required": None,
        "troubleshooting_failed": None,
        "escalation_dispatched": True if still_active else None,
        "dispatched_tickets": dispatched if still_active else None,
    }


def troubleshoot_success_node(state: AgentState):
    """Acknowledges that troubleshooting resolved the current issue (no ticket was created).

    Unlike escalation_resolved_node, this does NOT resolve any open tickets — it only
    resets the troubleshooting workflow state.  If there are open tickets from prior
    escalations, it appends a reminder so the operator is aware.
    """
    dispatched = list(state.get("dispatched_tickets") or [])

    response = "Glad to hear the issue is resolved! Let me know if there is anything else I can help you with."
    if dispatched:
        ticket_list = "\n".join(f"- {tid}" for tid in dispatched)
        response += (
            f"\n\nYou still have the following open tickets:\n{ticket_list}\n\n"
            "If any of these are also resolved, just let me know the ticket number."
        )

    return {
        "messages": [AIMessage(content=response)],
        "extracted_entities": {
            "troubleshooting_done": False,
            "troubleshooting_failed": False,
            "blast_radius": None,
            "blast_radius_asked": False,
            "clarify_asked": False,
        },
        "blast_radius": None,
        "escalation_required": None,
        "troubleshooting_failed": None,
        "escalation_dispatched": True if dispatched else None,
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
    "Present the scraped status information directly to the operator. Include the STATUS and the Details "
    "text exactly as returned by the tool. Then add the live status page link: https://setomaticsystems.com/status\n"
    "If the operator mentions they are experiencing a problem despite 'No Issue' status, THEN provide "
    "these local hub troubleshooting steps:\n"
    "   a. Power-cycle the SpyderWash Hub (unplug for 30 seconds, replug).\n"
    "   b. Verify the hub's Ethernet cable is firmly seated on both the hub and the router.\n"
    "   c. Confirm the router has internet access (open a browser on a connected device).\n"
    "   d. Check the hub's LED — solid green = connected; flashing amber = no internet.\n"
    "   e. If amber, reboot the router/modem and wait 5 minutes.\n"
    "   f. If still failing, contact Setomatic support at Support@setomaticsystems.com or (516) 990-4055.\n\n"
    "2. If the result says 'STATUS: Degraded' or contains an active outage event: "
    "confirm the global outage and advise the user to monitor https://setomaticsystems.com/status. "
    "No local troubleshooting is needed until the global issue is resolved.\n\n"
    "3. If the result says 'SYSTEM STATUS CHECK FAILED': tell the user you could not automatically "
    "check the status page and ask them to visit https://setomaticsystems.com/status directly.\n\n"

    "DATE RANGE RULE: When calling get_transaction_history, if the operator specifies a date range "
    "(e.g. 'transactions from March', 'last week', 'between Jan 1 and Jan 15'), pass start_date and "
    "end_date in YYYY-MM-DD format. If no dates are mentioned, omit them — the tool defaults to a "
    "rolling 6-month window. ALWAYS prefer the operator's explicit dates over the default.\n\n"

    "REFUND RULE: This agent does NOT process refunds. If the operator asks to refund a transaction, "
    "do NOT call any refund tools. Guide them to submit the refund request on the SpyderWash portal. "
    "Use KB/Bible guidance when available. You may still look up transaction history (including "
    "refunded history via include_refunds) as read-only support.\n\n"

    "REMOTE DEVICE RULE: The send_remote_device_command tool performs a DESTRUCTIVE action "
    "(reboot or card dispense). You MUST follow a 2-step confirmation flow:\n"
    "  STEP 1 — Confirm with the operator: Summarize the action you are about to take "
    "(device ID, command, and amount if Dispense) and ask for explicit confirmation. "
    "Example: 'I'm about to send a Reboot command to device ABC123. Please confirm with yes/no.'\n"
    "  STEP 2 — ONLY after the operator confirms with 'yes', 'confirm', 'proceed', or similar "
    "affirmative: call send_remote_device_command with the confirmed parameters.\n"
    "  If the operator says 'no' or 'cancel': acknowledge and do NOT call the tool.\n"
    "  For Dispense commands, the amount MUST be > 0. Ask the operator for the card value if not provided.\n\n"

    "POS TRANSACTION RULE: When calling get_pos_transactions, map the operator's natural language "
    "to the correct parameter values:\n"
    "  - Payment type (card_code): 'loyalty card' or 'loyalty' = 17, 'credit card' or 'credit' = 19, 'cash' = 20. Default: 17.\n"
    "  - Order type (order_type): 'all orders' = 1, 'sales only' or 'sale' = 2, 'WDF and PUD' = 3. Default: 1.\n"
    "  - Customer type (account_type): 'all customers' = 1, 'commercial' or 'commercial only' = 2, "
    "'non-commercial' or 'residential' = 3. Default: 1.\n"
    "  - Card number (card_no): If the user mentions a card number — even in masked format like "
    "'--****-1234', 'XXXX1234', 'ending in 1234', or 'last 4: 1234' — extract the last 4 digits "
    "and pass them as card_no. This ensures only that card's transactions are returned.\n"
    "  If the operator does not specify these filters, use the defaults (17, 1, 1). "
    "Always require a date range — ask the operator if not provided.\n\n"

    "KIOSK LOOKUP RULE: When calling get_kiosk_purchases or get_kiosk_recharges, both require "
    "a date range (start_date and end_date). If the operator does not specify dates, ask for them. "
    "Optional filters include location_name and imei (kiosk device ID).\n\n"

    "PAGINATION / SHOW MORE RULE: When a tool result says 'X more available. Say show more to see the next page', "
    "and the operator subsequently says 'show more', 'give me more', 'more records', 'more data', "
    "'next page', or similar — re-call the SAME tool with the SAME parameters but increment page_no by 1. "
    "Do NOT route these requests to RAG or out-of-domain. Do NOT ask the operator for parameters again. "
    "Always preserve all original filter arguments (dates, card_number, card_code, etc.) from the prior call."
)

_tool_llm = None

def _reset_tool_llm():
    """Force re-binding of tools on next invocation (call after adding/removing tools)."""
    global _tool_llm
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

    WHY A LOOP: Some workflows require sequential tool calls (e.g. confirm then
    send_remote_device_command). A single-shot implementation can leave AIMessages
    with tool_calls persisted without ToolMessages, causing API errors on later turns.

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

    from datetime import date as _date_type
    _today = _date_type.today().isoformat()
    _date_prefix = (
        f"TODAY'S DATE: {_today} — use this to resolve relative date expressions "
        "like 'last 3 months', 'this month', 'last week', 'this year', etc. "
        "Always calculate start_date and end_date relative to this date.\n\n"
    )
    base_system = {"role": "system", "content": _date_prefix + _TOOL_SYSTEM_PROMPT}
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

    if entities.get("escalation_confirmation_asked"):
        _confirm_positive = {"yes", "yeah", "yep", "yup", "ya", "yaa", "y", "si", "sí", "sure", "please", "ok", "okay"}
        _confirm_negative = {"no", "nope", "nah", "n", "cancel", "nevermind"}
        _confirm_phrases_yes = ("yes please", "go ahead", "escalate", "please escalate", "do it")
        _confirm_phrases_no = ("no thanks", "i'll call", "ill call", "contact them myself", "no need", "no,", "no.")
        # Strip punctuation and trailing letters from words for typo tolerance
        # (e.g., "no," → "no", "yese" → "yes", "yess" → "yes")
        _cleaned_words = set()
        for w in _last_text.split():
            cleaned = w.rstrip(".,!?;:")
            _cleaned_words.add(cleaned)
            # Strip trailing junk letters from common yes/no typos
            if cleaned.startswith("yes") and len(cleaned) <= 5:
                _cleaned_words.add("yes")
            if cleaned.startswith("no") and len(cleaned) <= 4 and cleaned not in ("none", "note", "norm"):
                _cleaned_words.add("no")
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

    # Ticket disambiguation follow-up: the user was asked "Which ticket is resolved?"
    # and is now providing a ticket ID or "all". Route back to escalation_resolved.
    if entities.get("ticket_resolution_asked"):
        return "escalation_resolved"

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

    # Post-escalation routing: check BOTH the state flag AND prior message content
    # to catch resolution/new-issue messages after a ticket was dispatched.
    _escalation_active = state.get("escalation_dispatched")
    _prior_mentions_ticket = prior_ai and any(
        marker in prior_ai.lower()
        for marker in ("critical escalation ticket", "already been dispatched", "escalation ticket", "dispatched to the on-call")
    )
    if _escalation_active or _prior_mentions_ticket:
        import re as _re_route
        latest = messages[-1].content if messages else ""
        if _user_indicates_resolved(latest):
            return "escalation_resolved"
        # A bare ticket ID (or ticket ID with resolution text) means the operator
        # is resolving a specific ticket — route to the resolve node.
        _has_open_tickets = bool(state.get("dispatched_tickets"))
        if _has_open_tickets and _re_route.search(r"TKT-[A-F0-9]+", latest, _re_route.IGNORECASE):
            return "escalation_resolved"
        # Allow API-action intents (balance, transactions, refund, status) to proceed
        # normally — operators shouldn't be trapped after escalation for unrelated actions.
        if state.get("api_action_required"):
            return "tool"
        # Allow new issue reports to start a fresh cycle instead of trapping them.
        if intent in _ESCALATION_WORKFLOW_INTENTS and len(latest.split()) >= 3:
            return "new_issue_after_escalation"
        if intent == "conversation_summary":
            return "summarize"
        # Any substantive new query (>3 words) passes through to normal routing
        # regardless of intent — operators shouldn't be trapped after escalation.
        if len(latest.split()) > 3:
            if intent == "greeting":
                return "greeting"
            if intent == "out_of_domain":
                return "out_of_domain"
            if state.get("hardware_lookup_attempted"):
                return "guardrail"
            if state.get("api_action_required"):
                return "tool"
            if intent in _ESCALATION_WORKFLOW_INTENTS:
                return "new_issue_after_escalation"
            return "rag"
        # Short messages: check for yes/no to "Did this resolve?" from prior RAG troubleshooting
        if entities.get("troubleshooting_done") and intent not in _ESCALATION_WORKFLOW_INTENTS:
            _pe_last = latest.strip().lower()
            _pe_pos = {"yes", "yeah", "yep", "yup", "ya", "yaa", "yah", "y", "si", "sí"}
            if _pe_last in _pe_pos or _user_indicates_resolved(latest):
                return "troubleshoot_success"
            _pe_neg_words = {"no", "nope", "nah"}
            if set(_pe_last.split()) & _pe_neg_words:
                return "confirm_escalation"
        return "post_escalation_ack"

    # Post-resolution closure: after "Glad to hear..." if the user replies with another
    # ticket ID, route to escalation_resolved so they can resolve the next ticket.
    if prior_ai and "glad to hear the issue is resolved" in prior_ai.lower():
        import re as _re_closure
        latest_raw = messages[-1].content if messages else ""
        _has_remaining = bool(state.get("dispatched_tickets"))
        if _has_remaining and _re_closure.search(r"TKT-[A-F0-9]+", latest_raw, _re_closure.IGNORECASE):
            return "escalation_resolved"
        if _is_resolution_message(latest_raw) and _has_remaining:
            return "escalation_resolved"
        latest = latest_raw.strip().lower()
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

    # Stateless resolution guard: if the user's message is clearly positive/resolved,
    # never let it fall through to the outage or escalation paths — regardless of state.
    # Skip when the troubleshooting_done flow is active (it has its own resolution handling).
    _latest_user = messages[-1].content if messages else ""
    if _is_resolution_message(_latest_user) and not entities.get("troubleshooting_done"):
        _has_any_tickets = bool(state.get("dispatched_tickets")) or state.get("escalation_dispatched")
        if _has_any_tickets:
            return "escalation_resolved"
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
                        content_lower = content.lower()
                        has_action_word = bool(set(content_lower.split()) & _issue_action_words)
                        if len(content) > 5 and (has_action_word or not _is_conversational_workflow_reply(content)):
                            _best_issue_msg = content_lower
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
                return "troubleshoot_success"
            # Ambiguous or gibberish reply — re-prompt for a clear Yes/No.
            return "workflow_reminder"

    # RAG-based troubleshooting follow-up: handle yes/no to "Did this resolve?"
    # for non-outage intents (technical_support routed through RAG, not the outage workflow).
    if (
        entities.get("troubleshooting_done")
        and intent not in _ESCALATION_WORKFLOW_INTENTS
        and not state.get("escalation_dispatched")
    ):
        _rag_pos = {"yes", "yeah", "yep", "yup", "ya", "yaa", "yah", "y", "si", "sí"}
        _rag_neg = {"no", "nope", "nah", "n"}
        if _last_text in _rag_pos or _user_indicates_resolved(_last_text):
            return "troubleshoot_success"
        _rag_neg_words = {"no", "nope", "nah", "not", "still", "broken", "failed", "down"}
        _rag_neg_phrases = ("not resolved", "not working", "still down", "didn't work", "same issue", "not fixed")
        if set(_last_text.split()) & _rag_neg_words or any(p in _last_text for p in _rag_neg_phrases):
            return "confirm_escalation"
        if len(_last_text.split()) > 3:
            pass  # Fall through to normal routing for unrelated new queries
        else:
            return "workflow_reminder"

    # API workflows: loyalty balance, transaction lookup, refund, system status check.
    if state.get("api_action_required"):
        return "tool"

    # All remaining intents (general_query, technical_support, etc.) go to RAG.
    return "rag"



def route_after_rag(state: AgentState) -> str:
    entities = state.get("extracted_entities") or {}
    if not entities.get("troubleshooting_done"):
        return "__end__"

    # Only intercept when the user is replying to a PRIOR "Did this resolve?"
    # prompt. Walk backwards past the RAG AIMessage to find the AI message
    # BEFORE the current RAG response — if that prior AI didn't ask
    # "Did this resolve?", the current RAG just generated a fresh answer and
    # we must show it (return __end__).
    messages = state.get("messages", [])
    human_text = ""
    prior_ai_text = ""
    ai_count = 0
    for msg in reversed(messages):
        if msg.type == "human" and not human_text:
            human_text = msg.content.lower()
        elif msg.type == "ai" and msg.content and str(msg.content).strip():
            ai_count += 1
            if ai_count == 2:
                prior_ai_text = msg.content.lower()
                break

    if "did this resolve" not in prior_ai_text:
        return "__end__"

    user_words = set(human_text.split())
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
    workflow.add_node("troubleshoot_success", troubleshoot_success_node)
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
            "troubleshoot_success": "troubleshoot_success",
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
    workflow.add_edge("troubleshoot_success", END)
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
