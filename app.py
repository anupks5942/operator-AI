import streamlit as st
import os
import uuid
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import your compiled LangGraph agent
# Note: Ensure this path correctly points to where you instantiated `compiled_graph`
from src.agent.graph import agent_app as compiled_graph

st.set_page_config(page_title="Setomatic Operator AI", page_icon="🕷️", layout="wide")
st.title("🕷️ SpyderWash Operator AI - MVP Demo")

# --- Session State Initialization ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    # Generate a unique thread ID for this session's multi-turn memory
    st.session_state.thread_id = str(uuid.uuid4())

# --- Sidebar Configuration & Diagnostics ---
with st.sidebar:
    st.header("🧠 AI Routing Diagnostics")
    st.markdown("*(Real-time backend state)*")
    st.divider()
    
    # Placeholders for dynamic updates during graph execution
    intent_placeholder = st.empty()
    guardrail_placeholder = st.empty()
    escalation_placeholder = st.empty()
    api_placeholder = st.empty()
    
    st.divider()
    st.markdown("""
    **Architecture Updated:**
    - UI: Streamlit
    - Orchestration: **LangGraph** State Machine
    - Tool Execution: FastAPI Mock Server / Web Scraper
    - Memory: SQLite Checkpointer
    """)

# --- Main Chat Interface ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask a troubleshooting question, check balance, or report an outage..."):
    # Add user message to UI state
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("AI is evaluating intent and routing..."):
        # Prepare the input state for LangGraph
        initial_state = {"messages": [("user", prompt)]}
        config = {"configurable": {"thread_id": st.session_state.thread_id}}
        
        try:
            # Execute the LangGraph state machine
            result = compiled_graph.invoke(initial_state, config=config)
            
            # Walk backwards to find the last AIMessage with actual text content.
            # When tool_node runs, the message sequence is:
            #   [AIMessage(tool_call, content=""), ToolMessage(result), AIMessage(summary, content="...")]
            # The very last message is the human-readable summary — but if the LLM
            # emitted only a tool_call with no follow-up text, content="" and we must
            # keep searching backwards for the nearest non-empty AIMessage.
            from langchain_core.messages import AIMessage as _AIMsg
            final_response = ""
            for msg in reversed(result.get("messages", [])):
                if isinstance(msg, _AIMsg) and msg.content and str(msg.content).strip():
                    final_response = str(msg.content).strip()
                    break
            if not final_response:
                final_response = "I processed your request but could not generate a response. Please try again."
            
            # --- Update Visual Diagnostics in Sidebar ---
            current_intent = result.get('current_intent', 'Unknown')
            intent_placeholder.info(f"**Detected Intent:**\n{current_intent}")
            
            if result.get('hardware_lookup_attempted', False):
                guardrail_placeholder.error("🛑 **Guardrail:**\nTRIGGERED (Action Blocked)")
            else:
                guardrail_placeholder.success("✅ **Guardrail:**\nCLEAR")
                
            if result.get('escalation_required', False):
                escalation_placeholder.error("🚨 **Escalation:**\nACTIVE (Simulating SMS Alert)")
            else:
                escalation_placeholder.success("✅ **Escalation:**\nNONE")
                
            api_req = result.get('api_action_required', False)
            if api_req:
                api_placeholder.warning(f"⚡ **API Tool Triggered:**\nTrue")
            else:
                api_placeholder.success(f"🔌 **API Tool Triggered:**\nFalse")

        except Exception as e:
            final_response = f"An error occurred while processing your request: {str(e)}"
            st.error(final_response)

    # Display AI response
    with st.chat_message("assistant"):
        st.markdown(final_response)
    st.session_state.messages.append({"role": "assistant", "content": final_response})