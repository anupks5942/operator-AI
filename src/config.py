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

# Base URL for the live SpyderWash/Setomatic production API
SETOMATIC_BASE_URL: str = os.getenv(
    "SETOMATIC_BASE_URL",
    "https://betasetomaticposwebapplication.spyderwash.com",
)

# Base URL for the local mock API server used during refund development
MOCK_BASE_URL: str = os.getenv(
    "MOCK_BASE_URL",
    "http://localhost:8001",
)

# When True, refund tools route to MOCK_BASE_URL; when False, they use SETOMATIC_BASE_URL
_use_mock_raw: str = os.getenv("USE_MOCK_REFUNDS", "true")
USE_MOCK_REFUNDS: bool = _use_mock_raw.strip().lower() not in ("false", "0", "no")

# OpenAI model configuration. One shared default keeps behavior consistent across
# routing, tool-calling, and RAG while still allowing per-node overrides later.
DEFAULT_OPENAI_MODEL: str = _env_str("OPENAI_MODEL", "gpt-4o-mini")
ROUTER_OPENAI_MODEL: str = _env_str("ROUTER_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
TOOL_OPENAI_MODEL: str = _env_str("TOOL_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
RAG_OPENAI_MODEL: str = _env_str("RAG_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
