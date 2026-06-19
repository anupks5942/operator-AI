import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

from src.agent.tools import (
    LoyaltyBalanceSchema, TransactionHistorySchema,
    RefundEligibilitySchema, RefundExecuteSchema,
    get_loyalty_balance, get_transaction_history,
    check_refund_eligibility, execute_refund,
    check_global_system_status,
    SETOMATIC_TOOLS,
)
from pydantic import ValidationError

# ── Schema binding check ──────────────────────────────────────────────────────
print("=== Schema binding check ===")
for t in SETOMATIC_TOOLS:
    schema = getattr(t, "args_schema", None)
    name = schema.__name__ if schema else "NONE"
    print(f"  {t.name:<35} args_schema: {name}")

# ── Valid inputs should be accepted ──────────────────────────────────────────
print()
print("=== Valid input acceptance ===")

r = LoyaltyBalanceSchema(card_number="LC-5555")
print(f"  LoyaltyBalanceSchema('LC-5555')        -> OK: {r.card_number}")

r = LoyaltyBalanceSchema(card_number="00000212")
print(f"  LoyaltyBalanceSchema('00000212')       -> OK: {r.card_number}")

r = TransactionHistorySchema(card_number="0001")
print(f"  TransactionHistorySchema('0001')       -> OK: {r.card_number}")

r = RefundEligibilitySchema(transaction_detail_id="TX-12345ABC")
print(f"  RefundEligibilitySchema('TX-12345ABC') -> OK: {r.transaction_detail_id}")

r = RefundExecuteSchema(transaction_detail_id="99001")
print(f"  RefundExecuteSchema('99001')           -> OK: {r.transaction_detail_id}")

# ── Invalid inputs must be rejected ──────────────────────────────────────────
print()
print("=== Invalid input rejection ===")

invalid_cases = [
    # (label,                 cls,                    kwargs,                                     expected reason)
    ("card too short",        LoyaltyBalanceSchema,   {"card_number": "XYZ"},                     "min_length"),
    ("card too long",         LoyaltyBalanceSchema,   {"card_number": "A" * 16},                  "max_length"),
    ("card illegal chars",    LoyaltyBalanceSchema,   {"card_number": "bad card!"},               "pattern"),
    ("card spaces",           TransactionHistorySchema, {"card_number": "LC 5555"},               "pattern"),
    ("tx_id spaces",          RefundEligibilitySchema,{"transaction_detail_id": "TX 99 BAD"},     "pattern"),
    ("tx_id empty",           RefundExecuteSchema,    {"transaction_detail_id": ""},              "min_length"),
    ("tx_id special chars",   RefundExecuteSchema,    {"transaction_detail_id": "TX@99#!"},       "pattern"),
]

all_pass = True
for label, cls, kwargs, _ in invalid_cases:
    try:
        cls(**kwargs)
        print(f"  FAIL [{label}]: accepted input that should have been rejected: {kwargs}")
        all_pass = False
    except ValidationError as exc:
        first_err = exc.errors()[0]["msg"]
        print(f"  PASS [{label}]: rejected -> {first_err}")

print()
print("All checks passed." if all_pass else "SOME CHECKS FAILED.")
