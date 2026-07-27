"""
Local demo chat UI (Streamlit).

Runs the agent inside this process (no need for the FastAPI server).
Good for developers trying questions and watching which step ran.

Run:
  uv run streamlit run app.py
"""
import streamlit as st
import uuid
import logging
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import AIMessage as _AIMsg
from src.utils.security import sanitize_user_text

# Load .env so API keys are ready before we import the graph.
load_dotenv()

# Configure logging so agent/tool log statements appear in the Streamlit terminal output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  |  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

# Same chat graph the production API uses.
from src.agent.graph import agent_app as compiled_graph

st.set_page_config(page_title="Setomatic Operator AI", page_icon="🕷️", layout="wide")
st.title("🕷️ SpyderWash Operator AI - MVP Demo")

# ── Timestamp helpers ─────────────────────────────────────────────────────────

def _now_ts() -> str:
    """Current time text for under each chat bubble."""
    return datetime.now().strftime("%b %d, %Y  %I:%M:%S %p")

def _render_ts(ts: str, align: str = "left") -> None:
    """Show a small timestamp under a chat message."""
    st.markdown(
        f"<p style='font-size:0.72rem; color:#888; margin-top:-8px; "
        f"text-align:{align};'>{ts}</p>",
        unsafe_allow_html=True,
    )

# Friendly labels shown while each graph step is running.
_NODE_LABELS: dict[str, str] = {
    "router":               "Classifying operator intent...",
    "tool_node":            "Executing system tool...",
    "rag_agent":            "Querying SpyderWash Knowledge Base...",
    "guardrail_node":       "Applying hardware status guardrail...",
    "escalation_node":      "Triggering escalation workflow...",
    "blast_radius_check":   "Confirming outage scope...",
    "troubleshoot_first":   "Querying SpyderWash Knowledge Base...",
    "escalation_resolved":  "Closing resolved support request...",
    "post_escalation_ack":  "Confirming escalation handoff...",
    "out_of_domain_node":   "Applying domain guardrail...",
    "pci_guardrail_node":   "Applying PCI compliance guardrail...",
    "greeting_node":        "Responding to greeting...",
    "summarize_node":       "Summarising the conversation...",
    "workflow_reminder_node": "Awaiting confirmation...",
    "new_issue_after_escalation": "Starting fresh support cycle...",
    "clarify_issue":              "Requesting more details...",
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
if "processing" not in st.session_state:
    st.session_state.processing = False
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None
if "routing_diagnostics" not in st.session_state:
    st.session_state.routing_diagnostics = {
        "current_intent": "Unknown",
        "hardware_lookup_attempted": False,
        "escalation_required": False,
        "api_action_required": False,
    }

def _render_routing_diagnostics(diag: dict) -> None:
    """Render sidebar routing diagnostics from persisted session state."""
    intent_placeholder.info(f"**Detected Intent:**\n{diag.get('current_intent', 'Unknown')}")

    if diag.get("hardware_lookup_attempted", False):
        guardrail_placeholder.error("🛑 **Guardrail:**\nTRIGGERED (Action Blocked)")
    else:
        guardrail_placeholder.success("✅ **Guardrail:**\nCLEAR")

    if diag.get("escalation_required", False):
        escalation_placeholder.error("🚨 **Escalation:**\nACTIVE (Simulating SMS Alert)")
    else:
        escalation_placeholder.success("✅ **Escalation:**\nNONE")

    if diag.get("api_action_required", False):
        api_placeholder.warning("⚡ **API Tool Triggered:**\nTrue")
    else:
        api_placeholder.success("🔌 **API Tool Triggered:**\nFalse")

# ── Sidebar: routing diagnostics ─────────────────────────────────────────────
with st.sidebar:
    if st.button("New Chat", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.routing_diagnostics = {
            "current_intent": "Unknown",
            "hardware_lookup_attempted": False,
            "escalation_required": False,
            "api_action_required": False,
        }
        st.rerun()

    st.header("🧠 AI Routing Diagnostics")
    st.markdown("*(Real-time backend state)*")
    st.divider()

    intent_placeholder     = st.empty()
    guardrail_placeholder  = st.empty()
    escalation_placeholder = st.empty()
    api_placeholder        = st.empty()

    _render_routing_diagnostics(st.session_state.routing_diagnostics)

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
# Disable input while the agent is processing to prevent duplicate submissions.
prompt = st.chat_input(
    "Ask a troubleshooting question, check balance, or report an outage...",
    disabled=st.session_state.processing,
)

if prompt and not st.session_state.processing:
    st.session_state.pending_input = prompt
    st.session_state.processing = True
    st.rerun()

# ── Process pending input (runs on the rerun with input disabled) ─────────────
if st.session_state.processing and st.session_state.pending_input:
    safe_input = sanitize_user_text(st.session_state.pending_input)
    st.session_state.pending_input = None
    user_ts = _now_ts()

    st.session_state.messages.append({"role": "user", "content": safe_input, "timestamp": user_ts})
    with st.chat_message("user"):
        st.markdown(safe_input)
        _render_ts(user_ts, align="right")

    initial_state = {"messages": [("user", safe_input)]}
    config        = {"configurable": {"thread_id": st.session_state.thread_id}}

    accumulated_state: dict = {}
    final_response           = ""

    try:
        with st.status("Agent is thinking...", expanded=True) as status:

            for chunk in compiled_graph.stream(
                initial_state,
                config=config,
                stream_mode="updates",
            ):
                for node_name, state_delta in chunk.items():
                    st.write(_node_label(node_name))

                    for key, value in state_delta.items():
                        if key == "messages":
                            existing = accumulated_state.get("messages", [])
                            accumulated_state["messages"] = existing + (
                                value if isinstance(value, list) else [value]
                            )
                        else:
                            accumulated_state[key] = value

                    # Refresh sidebar live during streaming
                    st.session_state.routing_diagnostics = {
                        "current_intent": accumulated_state.get("current_intent", "Unknown"),
                        "hardware_lookup_attempted": accumulated_state.get(
                            "hardware_lookup_attempted", False
                        ),
                        "escalation_required": accumulated_state.get(
                            "escalation_required", False
                        ),
                        "api_action_required": accumulated_state.get(
                            "api_action_required", False
                        ),
                    }
                    _render_routing_diagnostics(st.session_state.routing_diagnostics)

            final_response = _extract_final_response(accumulated_state)
            status.update(label="Task Complete", state="complete", expanded=False)

        # Persist final diagnostics so they survive the post-response rerun
        st.session_state.routing_diagnostics = {
            "current_intent": accumulated_state.get("current_intent", "Unknown"),
            "hardware_lookup_attempted": accumulated_state.get(
                "hardware_lookup_attempted", False
            ),
            "escalation_required": accumulated_state.get("escalation_required", False),
            "api_action_required": accumulated_state.get("api_action_required", False),
        }

    except Exception as exc:
        final_response = f"An error occurred while processing your request: {exc}"
        st.error(final_response)

    ai_ts = _now_ts()

    with st.chat_message("assistant"):
        st.markdown(final_response)
        _render_ts(ai_ts, align="left")

    st.session_state.messages.append({
        "role":      "assistant",
        "content":   final_response,
        "timestamp": ai_ts,
    })

    # Re-enable input after processing completes
    st.session_state.processing = False
    st.rerun()