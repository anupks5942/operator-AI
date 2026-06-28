import uvicorn
import uuid
from fastapi import FastAPI
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from src.api.routes import router
from src.agent.graph import agent_app as compiled_graph
from src.utils.security import sanitize_user_text

load_dotenv()

app = FastAPI(
    title="Setomatic KB RAG API",
    description="API for Setomatic Technical Support Agent",
    version="0.1.0"
)

app.include_router(router)


def stream_turn(query: str, thread_id: str, turn_label: str):
    """
    Execute one conversation turn using .stream() and print tokens as they arrive.
    This proves the pipeline is ready for low-latency voice/TTS integration.

    Args:
        query:      The user message for this turn.
        thread_id:  Stable identifier shared across all turns in one conversation.
        turn_label: Human-readable label for console output.
    """
    config = {"configurable": {"thread_id": thread_id}}
    state_input = {"messages": [("user", sanitize_user_text(query))]}

    print(f"\n{'='*65}")
    print(f"[{turn_label}] {query}")
    print(f"[thread_id]    {thread_id}")
    print(f"[STREAMING RESPONSE] ", end="", flush=True)

    final_state = None
    last_ai_content = ""

    # .stream() yields state snapshots after each node completes.
    # We watch for AIMessage chunks to print tokens progressively.
    for chunk in compiled_graph.stream(state_input, config=config, stream_mode="updates"):
        final_state = chunk
        # Each chunk is {node_name: state_delta}
        for node_name, delta in chunk.items():
            for msg in delta.get("messages", []):
                if isinstance(msg, AIMessage) and msg.content:
                    # Print only the new content delta (avoid reprinting tool calls)
                    new_text = msg.content[len(last_ai_content):]
                    print(new_text, end="", flush=True)
                    last_ai_content = msg.content

    print()  # newline after streamed content

    # Retrieve full final state for metadata display
    full_state = compiled_graph.get_state(config)
    sv = full_state.values if full_state else {}
    print(f"[Intent]               {sv.get('current_intent')}")
    print(f"[hardware_lookup]      {sv.get('hardware_lookup_attempted')}")
    print(f"[escalation_required]  {sv.get('escalation_required')}")
    print(f"[api_action_required]  {sv.get('api_action_required')}")
    print(f"[History length]       {len(sv.get('messages', []))} messages in thread")


def run_multi_turn_test():
    """
    Simulates a two-turn conversation using the same thread_id.

    Turn 1: Ask for loyalty card balance (card LC-5555).
    Turn 2: Ask for transaction history of "that same card" — the graph must
            resolve the card number from conversation history WITHOUT being told again.

    This validates that MemorySaver correctly persists state across turns.
    """
    thread_id = f"test-session-{uuid.uuid4().hex[:8]}"

    stream_turn(
        query="What is the balance on loyalty card LC-5555?",
        thread_id=thread_id,
        turn_label="TURN 1 >> Expected: Tool_Node (loyalty balance)",
    )

    stream_turn(
        query="Show me the last transactions for that same card.",
        thread_id=thread_id,
        turn_label="TURN 2 >> Expected: Tool_Node (transaction lookup, card inferred from history)",
    )

    stream_turn(
        query="Is SpyderWash down right now?",
        thread_id=thread_id,
        turn_label="TURN 3 >> Expected: Tool_Node (status lookup)",
    )


if __name__ == "__main__":
    run_multi_turn_test()
