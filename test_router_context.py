import sys, io
from dotenv import load_dotenv
load_dotenv()
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 1. Verify imports
from src.agent.router import semantic_router, SYSTEM_PROMPT, IntentClassification, _get_structured_llm
from src.agent.graph import agent_app
from src.agent.tools import SETOMATIC_TOOLS
print('Imports OK')
print('Tools:', [t.name for t in SETOMATIC_TOOLS])

llm = _get_structured_llm()

# Scenario A: assistant asked for card number, user replies with bare number
prior_assistant_a = 'Of course! To look up your transactions, could you please provide me with your loyalty card number?'
user_reply_a      = '00000212'

result_a = llm.invoke([
    {'role': 'system', 'content': SYSTEM_PROMPT},
    {'role': 'user',   'content': f'[PRIOR ASSISTANT MESSAGE]:\n{prior_assistant_a}\n\n[CURRENT USER MESSAGE]:\n{user_reply_a}'},
])

print()
print('--- Scenario A: card number reply after assistant asked for it ---')
print(f'  User input:          "{user_reply_a}"')
print(f'  Classified intent:   {result_a.intent}')
print(f'  api_action_required: {result_a.api_action_required}')
print(f'  extracted_entities:  {result_a.extracted_entities}')
print(f'  PASS (not general_query + api flag set):', result_a.intent != 'general_query' and result_a.api_action_required)

# Scenario B: refund confirmation 'yes'
prior_assistant_b = 'Transaction ID 99001 is eligible for a refund. Would you like me to proceed with processing the refund?'
user_reply_b      = 'yes'

result_b = llm.invoke([
    {'role': 'system', 'content': SYSTEM_PROMPT},
    {'role': 'user',   'content': f'[PRIOR ASSISTANT MESSAGE]:\n{prior_assistant_b}\n\n[CURRENT USER MESSAGE]:\n{user_reply_b}'},
])

print()
print('--- Scenario B: "yes" confirmation to proceed with refund ---')
print(f'  User input:          "{user_reply_b}"')
print(f'  Classified intent:   {result_b.intent}')
print(f'  api_action_required: {result_b.api_action_required}')
print(f'  extracted_entities:  {result_b.extracted_entities}')
print(f'  PASS (refund_request + api flag):', result_b.intent == 'refund_request' and result_b.api_action_required)

# Scenario C: isolated general query should NOT be affected
prior_assistant_c = 'How can I help you today?'
user_reply_c      = 'How do I set up a free wash program?'

result_c = llm.invoke([
    {'role': 'system', 'content': SYSTEM_PROMPT},
    {'role': 'user',   'content': f'[PRIOR ASSISTANT MESSAGE]:\n{prior_assistant_c}\n\n[CURRENT USER MESSAGE]:\n{user_reply_c}'},
])

print()
print('--- Scenario C: genuine general_query should stay general_query ---')
print(f'  User input:          "{user_reply_c}"')
print(f'  Classified intent:   {result_c.intent}')
print(f'  PASS (general_query):', result_c.intent == 'general_query')
