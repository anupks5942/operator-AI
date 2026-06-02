from typing import TypedDict, Annotated, Sequence, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # add_messages ensures messages are APPENDED (not overwritten) across turns.
    # This is what allows MemorySaver to accumulate the full conversation history.
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Scalar fields — Optional so partial state updates don't wipe earlier values
    context:                  Optional[str]
    current_intent:           Optional[str]
    hardware_lookup_attempted: Optional[bool]
    escalation_required:       Optional[bool]
    api_action_required:       Optional[bool]
    extracted_entities:        Optional[dict]
