import streamlit as st
import uuid
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import AIMessage as _AIMsg
from src.utils.security import sanitize_user_text

load_dotenv()

from src.agent.graph import agent_app as compiled_graph

st.set_page_config(page_title="Setomatic Operator AI", page_icon="🕷️", layout="wide")
st.title("🕷️ SpyderWash Operator AI - MVP Demo")

# ── Timestamp helpers ─────────────────────────────────────────────────────────

def _now_ts() -> str:
    """Return current local time with second precision."""
    return datetime.now().strftime("%b %d, %Y  %I:%M:%S %p")

def _render_ts(ts: str, align: str = "left") -> None:
    """Render a subtle timestamp caption beneath a chat bubble."""
    st.markdown(
        f"<p style='font-size:0.72rem; color:#888; margin-top:-8px; "
        f"text-align:{align};'>{ts}</p>",
        unsafe_allow_html=True,
    )

# ── Node-name → human-readable status label ───────────────────────────────────
# Each entry maps the exact LangGraph node name to a display string shown
# inside the st.status() block while that node is executing.
_NODE_LABELS: dict[str, str] = {
    "router":            "Classifying operator intent...",
    "tool_node":         "Executing system tool...",
    "rag_agent":         "Querying SpyderWash Knowledge Base...",
    "guardrail_node":    "Applying hardware status guardrail...",
    "escalation_node":   "Triggering escalation workflow...",
    "blast_radius_check": "Confirming outage scope...",
    "troubleshoot_first": "Querying SpyderWash Knowledge Base...",
    "escalation_resolved": "Closing resolved support request...",
    "post_escalation_ack": "Confirming escalation handoff...",
    "out_of_domain_node": "Applying domain guardrail...",
    "pci_guardrail_node": "Applying PCI compliance guardrail...",
}

def _node_label(node_name: str) -> str:
    """Return a display label for a streaming node update."""
    return _NODE_LABELS.get(node_name, f"⚙️ Running node: {node_name}...")

# ── Extract the final user-facing text from accumulated graph state ────────────
# walk backwards through all messages to find the last non-empty AIMessage.
# The ReAct tool loop saves sequences like:
#   AIMessage(tool_calls, content="") -> ToolMessage -> AIMessage(summary)
# The empty-content entries must be skipped.
def _extract_final_response(accumulated_state: dict) -> str:
    for msg in reversed(accumulated_state.get("messages", [])):
        if isinstance(msg, _AIMsg) and msg.content and str(msg.content).strip():
            return str(msg.content).strip()
    return "I processed your request but could not generate a response. Please try again."

# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

# ── Sidebar: routing diagnostics ─────────────────────────────────────────────
with st.sidebar:
    st.header("🧠 AI Routing Diagnostics")
    st.markdown("*(Real-time backend state)*")
    st.divider()

    intent_placeholder     = st.empty()
    guardrail_placeholder  = st.empty()
    escalation_placeholder = st.empty()
    api_placeholder        = st.empty()

    st.divider()
    st.markdown("""
    **Architecture:**
    - UI: Streamlit
    - Orchestration: **LangGraph** State Machine
    - Tool Execution: FastAPI Mock Server / Web Scraper
    - Memory: MemorySaver Checkpointer
    """)

# ── Render chat history ───────────────────────────────────────────────────────
for msg in st.session_state.messages:
    align = "right" if msg["role"] == "user" else "left"
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        _render_ts(msg.get("timestamp", ""), align=align)

# ── Handle new user input ─────────────────────────────────────────────────────
if prompt := st.chat_input("Ask a troubleshooting question, check balance, or report an outage..."):
    user_ts = _now_ts()

    # Scrub input to prevent visual UI leaks and backend PCI violations.
    safe_input = sanitize_user_text(prompt)

    # Persist and immediately render the user message
    st.session_state.messages.append({"role": "user", "content": safe_input, "timestamp": user_ts})
    with st.chat_message("user"):
        st.markdown(safe_input)
        _render_ts(user_ts, align="right")

    initial_state = {"messages": [("user", safe_input)]}
    config        = {"configurable": {"thread_id": st.session_state.thread_id}}

    # Accumulate the full state across all streamed node updates so we can
    # extract the final response and sidebar diagnostics after streaming ends.
    accumulated_state: dict = {}
    final_response           = ""

    try:
        # st.status() shows a live "Agent is thinking..." block that collapses
        # to "Task Complete" once the graph finishes streaming.
        with st.status("Agent is thinking...", expanded=True) as status:

            # stream_mode="updates" yields {node_name: state_delta} dicts —
            # one dict per node that executed, in execution order.
            for chunk in compiled_graph.stream(
                initial_state,
                config=config,
                stream_mode="updates",
            ):
                # Each chunk is a dict: {node_name: state_delta}
                for node_name, state_delta in chunk.items():
                    # Show a live human-readable label for the active node
                    st.write(_node_label(node_name))

                    # Merge the delta into accumulated_state so we always
                    # have the latest messages, intent, and flags available
                    for key, value in state_delta.items():
                        if key == "messages":
                            # Messages are a list; extend rather than overwrite
                            existing = accumulated_state.get("messages", [])
                            accumulated_state["messages"] = existing + (
                                value if isinstance(value, list) else [value]
                            )
                        else:
                            accumulated_state[key] = value

            # All nodes have finished — extract the final text response
            final_response = _extract_final_response(accumulated_state)

            # Collapse the status widget and mark completion
            status.update(label="Task Complete", state="complete", expanded=False)

        # ── Update sidebar diagnostics from final accumulated state ───────────
        current_intent = accumulated_state.get("current_intent", "Unknown")
        intent_placeholder.info(f"**Detected Intent:**\n{current_intent}")

        if accumulated_state.get("hardware_lookup_attempted", False):
            guardrail_placeholder.error("🛑 **Guardrail:**\nTRIGGERED (Action Blocked)")
        else:
            guardrail_placeholder.success("✅ **Guardrail:**\nCLEAR")

        if accumulated_state.get("escalation_required", False):
            escalation_placeholder.error("🚨 **Escalation:**\nACTIVE (Simulating SMS Alert)")
        else:
            escalation_placeholder.success("✅ **Escalation:**\nNONE")

        if accumulated_state.get("api_action_required", False):
            api_placeholder.warning("⚡ **API Tool Triggered:**\nTrue")
        else:
            api_placeholder.success("🔌 **API Tool Triggered:**\nFalse")

    except Exception as exc:
        final_response = f"An error occurred while processing your request: {exc}"
        st.error(final_response)

    ai_ts = _now_ts()

    # Render the assistant reply with timestamp
    with st.chat_message("assistant"):
        st.markdown(final_response)
        _render_ts(ai_ts, align="left")

    st.session_state.messages.append({
        "role":      "assistant",
        "content":   final_response,
        "timestamp": ai_ts,
    })