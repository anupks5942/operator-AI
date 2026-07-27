"""
Old request/response shapes for legacy API routes.

New work should use ChatRequest / ChatResponse in server.py instead.
"""
from pydantic import BaseModel
from typing import List, Optional


class QueryRequest(BaseModel):
    """Body for the old /query endpoint."""

    query: str  # What the operator asked
    session_id: Optional[str] = None  # Optional chat id (old path does not use it well)


class QueryResponse(BaseModel):
    """Reply from the old /query endpoint."""

    answer: str  # Agent text reply
    sources: Optional[List[str]] = None  # Optional source list (often empty)


class NotificationRequest(BaseModel):
    """Body for old /notify/sms and /notify/email."""

    to: str  # Phone or email destination
    message: str  # Text to send
