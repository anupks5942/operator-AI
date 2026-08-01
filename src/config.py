"""
Centralized configuration loader for the Setomatic support agent.

Reads environment variables from the .env file at project root.
All tool modules should import URL constants from here instead of
hardcoding URL strings directly.
"""
import os

from dotenv import load_dotenv

# Load variables from .env into the process environment before reading them
load_dotenv()


def _env_str(name: str, default: str) -> str:
    """Read a non-empty string env var, falling back to a default."""
    value = os.getenv(name, default).strip()
    return value or default


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean env var (true/1/yes vs false/0/no)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no")

# Base URL for the live SpyderWash/Setomatic production API
SETOMATIC_BASE_URL: str = os.getenv(
    "SETOMATIC_BASE_URL",
    "https://betasetomaticposwebapplication.spyderwash.com",
)

# LLM provider configuration. Switch providers through .env without code changes.
LLM_PROVIDER: str = _env_str("LLM_PROVIDER", "openai").lower()
OPENAI_MODEL: str = _env_str("OPENAI_MODEL", "gpt-4o-mini")
GROQ_MODEL: str = _env_str("GROQ_MODEL", "llama-3.3-70b-versatile")

# OpenAI embedding model for RAG vectorstore ingestion and retrieval.
OPENAI_EMBEDDING_MODEL: str = _env_str("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
# Must match the embedding model's output size (text-embedding-3-small = 1536).
EMBEDDING_DIMENSIONS: int = int(_env_str("EMBEDDING_DIMENSIONS", "1536"))

# Local on-disk Qdrant (replaces ./chroma_db). Built by: uv run python -m data_injection
QDRANT_PATH: str = _env_str("QDRANT_PATH", "./spyderwash_qdrant")
QDRANT_COLLECTION: str = _env_str("QDRANT_COLLECTION", "spyderwash_docs")
# Section 0 prompt cache written during data_injection.
SECTION0_CACHE_PATH: str = _env_str("SECTION0_CACHE_PATH", "./spyderwash_section0.txt")

# RAG retrieval: hybrid (default), vector, or vectorless.
RAG_RETRIEVAL_METHOD: str = _env_str("RAG_RETRIEVAL_METHOD", "hybrid").lower()
# Maximum BFS depth for recursive co-retrieval (SQLite rules).
CO_RETRIEVAL_MAX_DEPTH: int = int(_env_str("CO_RETRIEVAL_MAX_DEPTH", "3"))

# Escalation notifications — when False, NotificationService logs only (local dev).
USE_LIVE_NOTIFICATIONS: bool = _env_bool("USE_LIVE_NOTIFICATIONS", False)

# Twilio SMS (emergency store-down alerts)
TWILIO_ACCOUNT_SID: str = _env_str("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = _env_str("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER: str = _env_str("TWILIO_FROM_NUMBER", "")
ESCALATION_SMS_TO: str = _env_str("ESCALATION_SMS_TO", "")

# Mandrill SMTP (escalation email)
SMTP_HOST: str = _env_str("SMTP_HOST", "smtp.mandrillapp.com")
SMTP_PORT: int = int(_env_str("SMTP_PORT", "587"))
SMTP_USERNAME: str = _env_str("SMTP_USERNAME", "")
SMTP_PASSWORD: str = _env_str("SMTP_PASSWORD", "")
FROM_EMAIL: str = _env_str("FROM_EMAIL", "support@spyderwash.com")
ESCALATION_EMAIL: str = _env_str("ESCALATION_EMAIL", "support@setomaticsystems.com")
