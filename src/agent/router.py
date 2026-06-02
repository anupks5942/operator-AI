from pydantic import BaseModel, Field
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from src.agent.state import AgentState

SYSTEM_PROMPT = """You are a strict semantic router for a Setomatic/SpyderWash technical support agent.
Your ONLY job is to classify the user's intent and extract metadata. You do NOT answer questions.

## Intent Categories (you MUST use exactly one of these values):
- `general_query`           : General how-to questions about features, pricing, setup, or loyalty programs.
- `technical_support`       : Troubleshooting a specific machine error, card reader issue, or connectivity problem on one or a few machines.
- `hardware_status`         : User is asking for the LIVE or CURRENT status of a specific machine, hub, or port (e.g., "is port 4 offline?", "is washer #5 running?").
- `emergency_store_down`    : User states that their ENTIRE store, laundromat, or system is down, non-functional, or completely offline. This is a CRITICAL intent.
- `escalation_request`      : User explicitly asks to speak with a human, supervisor, or on-call technician.
- `loyalty_balance_query`   : User asks about their loyalty card balance, current dollar balance, points, or loyalty tier.
- `transaction_lookup`      : User asks to see recent transactions, payment history, or wash history on a loyalty card.
- `system_status_check`     : User asks if the SpyderWash/Setomatic GLOBAL SYSTEM is down, operational, or experiencing a service outage (e.g., "Is SpyderWash down?", "Is the system operational?", "Are there any outages?").

## CRITICAL CLASSIFICATION RULES - you MUST follow these exactly:
1. If the user says their WHOLE store, entire laundromat, whole system, or everything is down -> intent MUST be `emergency_store_down` AND `escalation_required` MUST be true. Do NOT classify this as `technical_support`.
2. If the user asks for the live/current/real-time status of a specific machine, hub, or port -> `hardware_lookup_attempted` MUST be true and intent MUST be `hardware_status`.
3. If the user explicitly asks for a human or supervisor -> intent MUST be `escalation_request` AND `escalation_required` MUST be true.
4. If the user asks about their loyalty card BALANCE, POINTS, or TIER -> intent MUST be `loyalty_balance_query` AND `api_action_required` MUST be true.
5. If the user asks to see RECENT TRANSACTIONS, PAYMENT HISTORY, or WASH HISTORY -> intent MUST be `transaction_lookup` AND `api_action_required` MUST be true.
6. If the user asks whether SpyderWash, Setomatic, or the GLOBAL SYSTEM is down/operational/experiencing outages -> intent MUST be `system_status_check` AND `api_action_required` MUST be true.
7. For all other questions, use the most appropriate remaining category.

## Field rules:
- `hardware_lookup_attempted`: true ONLY for `hardware_status` intent.
- `escalation_required`: true ONLY for `emergency_store_down` or `escalation_request` intents.
- `api_action_required`: true ONLY for `loyalty_balance_query`, `transaction_lookup`, or `system_status_check` intents.
- `extracted_entities`: extract any card numbers, last-4-digits, machine IDs, error codes, or location names mentioned.
"""

class IntentClassification(BaseModel):
    intent: str = Field(
        description="Classified intent. MUST be one of: general_query, technical_support, hardware_status, emergency_store_down, escalation_request, loyalty_balance_query, transaction_lookup, system_status_check."
    )
    hardware_lookup_attempted: bool = Field(
        description="True ONLY if the user is asking for the live/current status of a specific machine, hub, or port."
    )
    escalation_required: bool = Field(
        description="True ONLY if intent is emergency_store_down (whole store/system down) or escalation_request (user wants a human)."
    )
    api_action_required: bool = Field(
        description="True ONLY if intent is loyalty_balance_query, transaction_lookup, or system_status_check. Signals that a live API/web call must be made."
    )
    extracted_entities: Dict[str, Any] = Field(
        description="Any specific entities extracted from the query: card numbers, card last-4, machine IDs, error codes, location names."
    )

_structured_llm = None

def get_structured_llm():
    global _structured_llm
    if _structured_llm is None:
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        _structured_llm = llm.with_structured_output(IntentClassification, method="function_calling")
    return _structured_llm

def semantic_router(state: AgentState):
    """
    Analyzes the latest user message and updates the state with the classified intent,
    hardware flags, and extracted entities using GPT-4o.
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    latest_message = messages[-1].content

    structured_llm = get_structured_llm()
    result: IntentClassification = structured_llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": latest_message}
    ])

    return {
        "current_intent": result.intent,
        "hardware_lookup_attempted": result.hardware_lookup_attempted,
        "escalation_required": result.escalation_required,
        "api_action_required": result.api_action_required,
        "extracted_entities": result.extracted_entities
    }
