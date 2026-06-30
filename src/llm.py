"""Provider-independent construction of chat models."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from src.config import GROQ_MODEL, LLM_PROVIDER, OPENAI_MODEL


def create_chat_model(*, temperature: float = 0) -> BaseChatModel:
    """Create the configured provider's chat model."""
    if LLM_PROVIDER == "openai":
        return ChatOpenAI(model=OPENAI_MODEL, temperature=temperature)
    if LLM_PROVIDER == "groq":
        return ChatGroq(model=GROQ_MODEL, temperature=temperature)
    raise ValueError(
        f"Unsupported LLM_PROVIDER {LLM_PROVIDER!r}; expected 'openai' or 'groq'."
    )
