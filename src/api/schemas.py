from pydantic import BaseModel
from typing import List, Optional

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

class QueryResponse(BaseModel):
    answer: str
    sources: Optional[List[str]] = None

class NotificationRequest(BaseModel):
    to: str
    message: str
