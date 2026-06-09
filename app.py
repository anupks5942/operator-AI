import streamlit as st
import os
import uuid
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import your compiled LangGraph agent
from src.agent.graph import agent_app as compiled_graph

st.set_page_config(page_title="Setomatic Operator AI", page_icon="🕷️", layout="wide")
st.title("🕷️ SpyderWash Operator AI - MVP Demo")

# ── Timestamp helper ──────────────────────────────────────────────────────────

def _now_ts() -> str:
    """Return current local time as a compact, human-readable string."""
    return datetime.now().strftime("%b %d, %Y  %I:%M:%S %p")

def _render_ts(ts: str, align: str = "left") -> None:
    """Render a timestamp as a subtle, small caption under a chat bubble."""
    st.markdown(
        f"<p style='font-size:0.72rem; color:#888; margin-top:-8px; "
        f"text-align:{align};'>{ts}</p>",
        unsafe_allow_html=True,
    )

# ── Session State Initialization ──────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

# ── Sidebar Configuration & Diagnostics ──────────────────────────────────────
with st.sidebar:
    st.header("🧠 AI Routing Diagnostics")
    st.markdown("*(Real-time backend state)*")
    st.divider()

    # Placeholders for dynamic updates during graph execution
    intent_placeholder    = st.empty()
    guardrail_placeholder = st.empty()
    escalation_placeholder = st.empty()
    api_placeholder       = st.empty()

    st.divider()
    st.markdown("""
    **Architecture Updated:**
    - UI: Streamlit
    - Orchestration: **LangGraph** State Machine
    - Tool Execution: FastAPI Mock Server / Web Scraper
    - Memory: SQLite Checkpointer
    """)

# ── Main Chat Interface — render history ──────────────────────────────────────
for msg in st.session_state.messages:
    align = "right" if msg["role"] == "user" else "left"
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        _render_ts(msg.get("timestamp", ""), align=align)

# ── Handle new user input ─────────────────────────────────────────────────────
if prompt := st.chat_input("Ask a troubleshooting question, check balance, or report an outage..."):
    user_ts = _now_ts()

    # Append & immediately render user message with timestamp
    st.session_state.messages.append({
        "role":      "user",
        "content":   prompt,
        "timestamp": user_ts,
    })
    with st.chat_message("user"):
        st.markdown(prompt)
        _render_ts(user_ts, align="right")

    with st.spinner("AI is evaluating intent and routing..."):
        initial_state = {"messages": [("user", prompt)]}
        config        = {"configurable": {"thread_id": st.session_state.thread_id}}

        try:
            result = compiled_graph.invoke(initial_state, config=config)

            # Walk backwards to find the last AIMessage with actual text content.
            # When tool_node runs, the sequence is:
            #   AIMessage(tool_calls, content="") → ToolMessage → AIMessage(summary)
            # The empty-content AIMessage must be skipped.
            from langchain_core.messages import AIMessage as _AIMsg
            final_response = ""
            for m in reversed(result.get("messages", [])):
                if isinstance(m, _AIMsg) and m.content and str(m.content).strip():
                    final_response = str(m.content).strip()
                    break
            if not final_response:
                final_response = "I processed your request but could not generate a response. Please try again."

            # --- Update Visual Diagnostics in Sidebar ---
            current_intent = result.get("current_intent", "Unknown")
            intent_placeholder.info(f"**Detected Intent:**\n{current_intent}")

            if result.get("hardware_lookup_attempted", False):
                guardrail_placeholder.error("🛑 **Guardrail:**\nTRIGGERED (Action Blocked)")
            else:
                guardrail_placeholder.success("✅ **Guardrail:**\nCLEAR")

            if result.get("escalation_required", False):
                escalation_placeholder.error("🚨 **Escalation:**\nACTIVE (Simulating SMS Alert)")
            else:
                escalation_placeholder.success("✅ **Escalation:**\nNONE")

            api_req = result.get("api_action_required", False)
            if api_req:
                api_placeholder.warning("⚡ **API Tool Triggered:**\nTrue")
            else:
                api_placeholder.success("🔌 **API Tool Triggered:**\nFalse")

        except Exception as e:
            final_response = f"An error occurred while processing your request: {str(e)}"
            st.error(final_response)

    ai_ts = _now_ts()

    # Render AI response with timestamp
    with st.chat_message("assistant"):
        st.markdown(final_response)
        _render_ts(ai_ts, align="left")

    st.session_state.messages.append({
        "role":      "assistant",
        "content":   final_response,
        "timestamp": ai_ts,
    })