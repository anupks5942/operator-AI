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
