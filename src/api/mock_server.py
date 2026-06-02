"""
Mock FastAPI server simulating Setomatic backend API endpoints.
Run this independently: uv run uvicorn src.api.mock_server:mock_app --port 8001 --reload
"""
import random
import string
from datetime import datetime, timedelta
from fastapi import FastAPI
from pydantic import BaseModel

mock_app = FastAPI(
    title="Setomatic Mock Backend API",
    description="Mock endpoints simulating loyalty and transaction data.",
    version="1.0.0",
)

# ── Request schemas ───────────────────────────────────────────────────────────

class LoyaltyBalanceRequest(BaseModel):
    card_number: str

class TransactionLookupRequest(BaseModel):
    card_ending: str

# ── Helpers ───────────────────────────────────────────────────────────────────

def _random_tx(i: int, card_ending: str) -> dict:
    days_ago = random.randint(1, 60)
    date = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    tx_type = random.choice(["wash_cycle", "reload", "free_wash_redemption"])
    amount = round(random.uniform(1.50, 8.00), 2)
    return {
        "tx_id": f"TX-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}",
        "date": date,
        "type": tx_type,
        "amount_usd": amount if tx_type != "free_wash_redemption" else 0.00,
        "card_ending": card_ending,
        "machine_id": f"W{random.randint(1, 12)}",
    }

# ── Endpoints ─────────────────────────────────────────────────────────────────

@mock_app.post("/api/v1/loyalty/balance")
def get_loyalty_balance(request: LoyaltyBalanceRequest):
    """
    Returns a mock loyalty card balance for a given card number.
    """
    balance = round(random.uniform(0.00, 150.00), 2)
    return {
        "status": "success",
        "card_number": request.card_number,
        "balance_usd": balance,
        "loyalty_tier": "Gold" if balance > 50 else "Standard",
        "points": int(balance * 10),
    }


@mock_app.post("/api/v1/transactions/lookup")
def get_transaction_history(request: TransactionLookupRequest):
    """
    Returns a mock transaction history for the last 5 transactions on a card.
    """
    transactions = [_random_tx(i, request.card_ending) for i in range(5)]
    transactions.sort(key=lambda x: x["date"], reverse=True)
    return {
        "status": "success",
        "card_ending": request.card_ending,
        "transaction_count": len(transactions),
        "transactions": transactions,
    }
