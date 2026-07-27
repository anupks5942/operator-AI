"""
Old entry file — do not use for new work.

Use:
  - src/api/server.py for the real API
  - app.py for the Streamlit demo

This file still has an old FastAPI app and a small console test.
"""
import uvicorn
import uuid
from fastapi import FastAPI
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from src.api.routes import router
from src.agent.graph import agent_app as compiled_graph
from src.utils.security import sanitize_user_text

load_dotenv()

# Old FastAPI app (replaced by src.api.server:app).
app = FastAPI(
    title="Setomatic KB RAG API",
    description="API for Setomatic Technical Support Agent",
    version="0.1.0"
)

# Old /query and /notify routes.
app.include_router(router)


def stream_turn(query: str, thread_id: str, turn_label: str):
    """
    Run one chat turn and print the answer as it streams.

    query: what the user said
    thread_id: same id keeps memory across turns
    turn_label: label printed in the console
    """
    config = {"configurable": {"thread_id": thread_id}}
    state_input = {"messages": [("user", sanitize_user_text(query))]}

    print(f"\n{'='*65}")
    print(f"[{turn_label}] {query}")
    print(f"[thread_id]    {thread_id}")
    print(f"[STREAMING RESPONSE] ", end="", flush=True)

    final_state = None
    last_ai_content = ""

    # Each chunk is one graph step finishing.
    for chunk in compiled_graph.stream(state_input, config=config, stream_mode="updates"):
        final_state = chunk
        for node_name, delta in chunk.items():
            for msg in delta.get("messages", []):
                if isinstance(msg, AIMessage) and msg.content:
                    # Print only new text, not repeats.
                    new_text = msg.content[len(last_ai_content):]
                    print(new_text, end="", flush=True)
                    last_ai_content = msg.content

    print()

    full_state = compiled_graph.get_state(config)
    sv = full_state.values if full_state else {}
    print(f"[Intent]               {sv.get('current_intent')}")
    print(f"[hardware_lookup]      {sv.get('hardware_lookup_attempted')}")
    print(f"[escalation_required]  {sv.get('escalation_required')}")
    print(f"[api_action_required]  {sv.get('api_action_required')}")
    print(f"[History length]       {len(sv.get('messages', []))} messages in thread")


def run_multi_turn_test():
    """
    Quick console test with two turns on the same thread.

    Turn 1 asks for a card balance.
    Turn 2 asks for transactions on "that same card" — memory must remember the card.
    """
    thread_id = f"test-session-{uuid.uuid4().hex[:8]}"

    stream_turn(
        query="What is the balance on loyalty card LC-5555?",
        thread_id=thread_id,
        turn_label="TURN 1 — Loyalty Balance",
    )
    stream_turn(
        query="Show me the recent transactions for that same card",
        thread_id=thread_id,
        turn_label="TURN 2 — Transactions (entity continuity)",
    )


if __name__ == "__main__":
    # When you run: python main.py
    run_multi_turn_test()
