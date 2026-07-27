"""
Shared memory for one chat session.

Every node reads and updates this state. LangGraph saves it per session_id.
"""
from typing import TypedDict, Annotated, Sequence, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def merge_dicts(old: dict | None, new: dict | None) -> dict:
    """
    Join two dictionaries.

    Why: if turn 2 only sends {confirmation: True}, we still keep card_number
    from turn 1. Without this merge, turn 1 data would be wiped.
    """
    return {**(old or {}), **(new or {})}


class AgentState(TypedDict):
    """All the fields we remember for one operator chat."""

    # Chat history. New messages are added, not replaced.
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Old optional text field. Rarely used now.
    context:                   Optional[str]
    # What kind of ask this was (e.g. machine_down, loyalty balance).
    current_intent:            Optional[str]
    # True if they asked for live machine status (we refuse that).
    hardware_lookup_attempted: Optional[bool]
    # True if this looks like an outage that may need escalation.
    escalation_required:       Optional[bool]
    # True if we must call a live API tool (balance, transactions, etc.).
    api_action_required:       Optional[bool]
    # "single_machine" or "entire_location" — how big the outage is.
    blast_radius:              Optional[str]
    # True if the operator said the fix steps did not work.
    troubleshooting_failed:    Optional[bool]
    # True after we already sent a support ticket (email/SMS).
    escalation_dispatched:     Optional[bool]
    # Open ticket IDs still waiting to be closed (like TKT-ABC123).
    dispatched_tickets:        Optional[list]
    # Ticket ID → email id, so resolve emails can reply in the same thread.
    ticket_email_ids:          Optional[dict]
    # Every ticket created in this chat (kept even after resolve).
    all_session_tickets:       Optional[list]
    # Operator contact info from the frontend (for the ticket email).
    operator_id:               Optional[int]
    operator_name:             Optional[str]
    operator_email:            Optional[str]
    operator_phone:            Optional[str]
    # Short text of the last ticket issue (used to spot duplicate reports).
    last_ticket_summary:       Optional[str]
    # Size of the last ticket outage (also used for duplicate checks).
    last_ticket_blast_radius:  Optional[str]
    # Extra notes the operator adds after a ticket was sent.
    ticket_notes:              Optional[list]
    # Callback phone number if they give one after escalation.
    callback_number:           Optional[str]
    # Bag of small facts: card number, dates, device id, flags, etc.
    extracted_entities: Annotated[dict, merge_dicts]
