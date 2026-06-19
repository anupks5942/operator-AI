from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from src.agent.state import AgentState
from src.agent.nodes import retrieve_and_generate, guardrail_node, handle_out_of_domain
from src.agent.router import semantic_router
from src.agent.tools import SETOMATIC_TOOLS

# ── Inline node definitions ───────────────────────────────────────────────────

def escalation_node(state: AgentState):
    """
    Triggered when an emergency is detected (e.g., entire store down).
    Appends a system-level emergency alert to the state.
    """
    alert = (
        "[SYSTEM] Emergency detected. Generating SMS payload with ticket number "
        "for on-call technician."
    )
    return {"messages": [AIMessage(content=alert)]}


_TOOL_SYSTEM_PROMPT = (
    "You are a Setomatic/SpyderWash technical support agent with access to tools. "
    "Use the tools available to you to answer the user's question accurately.\n\n"

    "CRITICAL OUTAGE RULE: If the user reports a system outage OR asks whether SpyderWash or Setomatic "
    "is down, you MUST call the check_global_system_status tool FIRST before doing anything else. "
    "After receiving the tool result, follow these rules EXACTLY:\n\n"
    "1. If the result says '[Setomatic Systems] STATUS: No Issue' or similar 'No Issue'/'Operational': "
    "tell the user the global system is fully operational. Their issue is a LOCAL network problem. "
    "Provide these hub troubleshooting steps:\n"
    "   a. Power-cycle the SpyderWash Hub (unplug for 30 seconds, replug).\n"
    "   b. Verify the hub's Ethernet cable is firmly seated on both the hub and the router.\n"
    "   c. Confirm the router has internet access (open a browser on a connected device).\n"
    "   d. Check the hub's LED — solid green = connected; flashing amber = no internet.\n"
    "   e. If amber, reboot the router/modem and wait 5 minutes.\n"
    "   f. If still failing, contact Setomatic support at Support@setomaticsystems.com or (516) 990-4055.\n\n"
    "2. If the result contains 'HISTORICAL INCIDENT': the tool only has stale backup data. "
    "Tell the user: 'I checked our backup status source but the data is from a past incident that "
    "has likely been resolved. The current Setomatic status page shows no active outages. "
    "Please verify at https://setomaticsystems.com/status.' Then provide the local troubleshooting steps above.\n\n"
    "3. If the result says 'STATUS: Degraded' or contains an active outage event with a recent date: "
    "confirm the global outage and advise the user to monitor https://setomaticsystems.com/status. "
    "No local troubleshooting is needed until the global issue is resolved.\n\n"
    "4. If the result says 'SYSTEM STATUS CHECK FAILED': tell the user you could not automatically "
    "check the status page and ask them to visit https://setomaticsystems.com/status directly.\n\n"

    "CRITICAL REFUND RULE: If the user asks for a refund on any transaction, you MUST follow this "
    "exact 3-step sequential workflow. Do NOT skip or reorder any step:\n\n"
    "  STEP 1 — Call get_transaction_history with the user's loyalty card number to retrieve recent "
    "transactions. Each transaction line includes its ID in the format [ID:xxxx]. Identify the "
    "transactionDetailId for the transaction the user wants refunded. If the user has not provided "
    "a card number, ask for it before proceeding.\n\n"
    "  STEP 2 — Call check_refund_eligibility with that transactionDetailId. Parse the result:\n"
    "    - If the result says 'IS eligible': inform the user and proceed to Step 3.\n"
    "    - If the result says 'is NOT eligible': inform the user of the reason and STOP. "
    "Do NOT call execute_refund under any circumstances if eligibility is false.\n\n"
    "  STEP 3 — ONLY if Step 2 confirmed eligibility: call execute_refund with the same "
    "transactionDetailId. Report the refund confirmation message and receipt number "
    "(e.g. REF-998877) back to the user."
)

_tool_llm = None

def _get_tool_llm():
    global _tool_llm
    if _tool_llm is None:
        _tool_llm = ChatOpenAI(model="gpt-4o", temperature=0).bind_tools(SETOMATIC_TOOLS)
    return _tool_llm

def tool_node(state: AgentState):
    """
    Tool_Node: Executes tools via a ReAct-style loop until the LLM produces
    a plain-text response (no more tool_calls).

    WHY A LOOP: The refund workflow requires sequential tool calls:
      get_transaction_history → check_refund_eligibility → execute_refund
    A single-shot implementation (invoke → tool → summarize) causes the
    "summarize" LLM call to itself return tool_calls=[...] for the next step.
    That AIMessage gets persisted to state WITHOUT a ToolMessage response,
    causing OpenAI 400 errors on subsequent turns.

    The loop guarantees that every AIMessage with tool_calls is ALWAYS
    followed by its ToolMessages before the next LLM call — maintaining a
    valid OpenAI message sequence at all times.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"messages": [AIMessage(content="No query to process.")]}

    tool_map      = {t.name: t for t in SETOMATIC_TOOLS}
    llm_with_tools = _get_tool_llm()

    # ── Build entity hint from router state ───────────────────────────────────
    entities   = state.get("extracted_entities") or {}
    intent     = state.get("current_intent") or ""
    hint_parts = []

    if intent:
        hint_parts.append(f"Active workflow intent: {intent}.")
    if entities:
        entity_lines = "\n".join(
            f"  - {k}: {v}" for k, v in entities.items() if v is not None
        )
        hint_parts.append(
            "The router has already extracted the following entities from the "
            "user's input. Use them directly as tool arguments — do NOT ask the "
            f"user for them again:\n{entity_lines}"
        )

    base_system = {"role": "system", "content": _TOOL_SYSTEM_PROMPT}
    msgs        = [base_system]
    if hint_parts:
        msgs.append({
            "role":    "system",
            "content": "EXTRACTED CONTEXT (use immediately):\n" + "\n".join(hint_parts),
        })
    msgs += list(messages)

    # ── ReAct loop ────────────────────────────────────────────────────────────
    # `new_messages` collects everything added THIS invocation (appended to state).
    # `msgs`         is the growing working context sent to the LLM each round.
    new_messages   = []
    MAX_ITERATIONS = 6   # safety cap — prevents runaway tool chains

    for _ in range(MAX_ITERATIONS):
        ai_response = llm_with_tools.invoke(msgs)

        # Always accumulate the AI response
        new_messages.append(ai_response)
        msgs.append(ai_response)

        # If the LLM produced text (no tool calls), we are done
        if not ai_response.tool_calls:
            break

        # Execute every tool call; always add a ToolMessage (even on failure)
        # so the message sequence is ALWAYS valid for OpenAI
        for tool_call in ai_response.tool_calls:
            tool_fn = tool_map.get(tool_call["name"])
            if tool_fn:
                try:
                    result = tool_fn.invoke(tool_call["args"])
                except Exception as exc:
                    result = f"Tool '{tool_call['name']}' raised an error: {exc}"
            else:
                result = (
                    f"Unknown tool '{tool_call['name']}'. "
                    f"Available tools: {list(tool_map.keys())}"
                )

            tool_msg = ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
            new_messages.append(tool_msg)
            msgs.append(tool_msg)

    return {"messages": new_messages}



# ── Conditional routing ───────────────────────────────────────────────────────

def route_after_classifier(state: AgentState) -> str:
    """
    Priority-ordered conditional routing after the Intent Classifier.

    Priority order:
      1. Hardware exception intents  -> RAG_Node   (hardcoded; API tools forbidden)
      2. hardware_lookup_attempted   -> Guardrail_Node  (hard block on live status queries)
      3. escalation_required         -> Escalation_Node (emergency path)
      4. api_action_required         -> Tool_Node       (live API / web call)
      5. default                     -> RAG_Node
    """
    intent = state.get("current_intent", "")

    # Out-of-domain and prompt injection: route directly to the static refusal node.
    if intent == "out_of_domain":
        return "out_of_domain"

    # Kiosk frozen/unresponsive: always surface KB manual guidance, never call API tools.
    if intent == "kiosk_not_responding":
        return "rag"

    # Machines not starting: always surface KB manual guidance, never call API tools.
    if intent == "machines_not_starting":
        return "rag"

    # Multiple machines offline simultaneously: surface hub/network KB steps, not API tools.
    if intent == "multiple_machines_offline":
        return "rag"

    # Hard block: live hardware status requests are refused by the guardrail node.
    if state.get("hardware_lookup_attempted"):
        return "guardrail"

    # Emergency escalation: whole store down or operator explicitly requests a human.
    if state.get("escalation_required"):
        return "escalation"

    # API workflows: loyalty balance, transaction lookup, refund, system status check.
    if state.get("api_action_required"):
        return "tool"

    # All remaining intents (general_query, technical_support, etc.) go to RAG.
    return "rag"


# ── Graph compilation ─────────────────────────────────────────────────────────

def create_agent_graph():
    """
    Compiles and returns the LangGraph state graph with MemorySaver checkpointing.
    Each conversation thread is identified by a 'thread_id' in the run config,
    allowing multi-turn state persistence across separate .invoke() / .stream() calls.
    """
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("router",            semantic_router)
    workflow.add_node("guardrail_node",    guardrail_node)
    workflow.add_node("escalation_node",   escalation_node)
    workflow.add_node("tool_node",         tool_node)
    workflow.add_node("rag_agent",         retrieve_and_generate)
    # Static refusal node: no LLM, no API — hardcoded response for off-topic or adversarial input.
    workflow.add_node("out_of_domain_node", handle_out_of_domain)

    # Entry point
    workflow.set_entry_point("router")

    # 5-way conditional routing (out_of_domain checked first)
    workflow.add_conditional_edges(
        "router",
        route_after_classifier,
        {
            "out_of_domain": "out_of_domain_node",
            "guardrail":     "guardrail_node",
            "escalation":    "escalation_node",
            "tool":          "tool_node",
            "rag":           "rag_agent",
        }
    )

    # Terminal edges
    workflow.add_edge("out_of_domain_node", END)
    workflow.add_edge("guardrail_node",     END)
    workflow.add_edge("escalation_node",    END)
    workflow.add_edge("tool_node",          END)
    workflow.add_edge("rag_agent",          END)

    # Attach in-memory checkpointer for multi-turn persistence
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


# Compiled instance (shared across the FastAPI app lifetime)
agent_app = create_agent_graph()
