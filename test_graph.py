from src.agent.graph import agent_app
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# Load environment variables (ensure OPENAI_API_KEY and GROQ_API_KEY are set)
load_dotenv()

def test_graph(query: str):
    print(f"\n--- Testing Query: '{query}' ---")
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "context": ""
    }
    
    # Invoke LangGraph agent
    try:
        final_state = agent_app.invoke(initial_state)
        
        # Check router output
        intent = final_state.get("current_intent")
        hardware_flag = final_state.get("hardware_lookup_attempted")
        print(f"Router Intent: {intent}")
        print(f"Hardware Lookup Attempted: {hardware_flag}")
        
        # Extract the final answer
        messages = final_state.get("messages", [])
        if messages:
            answer = messages[-1].content
            print(f"Agent Response:\n{answer}")
        else:
            print("No response generated.")
            
    except Exception as e:
        print(f"Error during graph execution: {e}")

if __name__ == "__main__":
    # Test 1: Hardware lookup (Should trigger guardrail)
    test_graph("Is washer #5 currently running or available?")
    
    # Test 2: Standard KB Question (Should trigger RAG)
    test_graph("How do I issue a partial refund?")
