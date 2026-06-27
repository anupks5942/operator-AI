from typing import TypedDict, Annotated, Sequence, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# merge_dicts is used as a LangGraph reducer so that each router turn ADDS new
# entities on top of previously extracted ones instead of replacing the whole dict.
# Without this, a turn-2 update of {confirmation: True} would silently wipe the
# card_number extracted in turn 1, breaking multi-step workflows like refunds.
def merge_dicts(old: dict | None, new: dict | None) -> dict:
    return {**(old or {}), **(new or {})}


class AgentState(TypedDict):
    # add_messages ensures messages are APPENDED (not overwritten) across turns.
    # This is what allows MemorySaver to accumulate the full conversation history.
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Scalar fields — Optional so partial state updates don't wipe earlier values
    context:                   Optional[str]
    current_intent:            Optional[str]
    hardware_lookup_attempted: Optional[bool]
    escalation_required:       Optional[bool]
    api_action_required:       Optional[bool]
    # Tracks whether the downtime is a single machine or location-wide — drives RAG vs escalation routing.
    blast_radius:              Optional[str]
    # Explicitly persists whether the operator confirmed troubleshooting failed, decoupled from extracted_entities.
    troubleshooting_failed:    Optional[bool]
    # Set True when escalation_node dispatches email/SMS for this session turn.
    escalation_dispatched:     Optional[bool]
    # Operator contact info passed from the frontend API (optional).
    operator_id:               Optional[int]
    operator_name:             Optional[str]
    operator_email:            Optional[str]
    operator_phone:            Optional[str]
    # merge_dicts reducer merges partial entity updates across turns instead of
    # overwriting the entire dict, preserving entities from earlier workflow steps.
    extracted_entities: Annotated[dict, merge_dicts]
