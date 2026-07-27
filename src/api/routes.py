"""
Old API routes — do not build new features here.

Use server.py instead:
  POST /api/v1/agent/chat
  GET  /health
"""
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from src.api.schemas import QueryRequest, QueryResponse, NotificationRequest
from src.agent.graph import agent_app
from src.services.notifications import NotificationService
from src.utils.security import sanitize_user_text

# Router used by the old main.py app.
router = APIRouter()


@router.get("/health")
def health_check():
    """Simple "is the process up?" check."""
    return {"status": "healthy"}


@router.post("/query", response_model=QueryResponse)
def query_agent(request: QueryRequest):
    """
    Old one-shot chat endpoint.

    Prefer /api/v1/agent/chat so multi-turn memory works properly.
    """
    try:
        # Hide card numbers before the agent sees the text.
        initial_state = {
            "messages": [HumanMessage(content=sanitize_user_text(request.query))],
            "context": "",
        }

        final_state = agent_app.invoke(initial_state)

        messages = final_state.get("messages", [])
        if messages:
            answer = messages[-1].content
        else:
            answer = "No response generated."

        return QueryResponse(answer=answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notify/sms")
def notify_sms(request: NotificationRequest):
    """Old direct SMS send. Prefer creating tickets through the normal chat flow."""
    success = NotificationService.send_sms(to_number=request.to, message=request.message)
    return {"success": success}


@router.post("/notify/email")
def notify_email(request: NotificationRequest):
    """Old direct email send. Prefer creating tickets through the normal chat flow."""
    success = NotificationService.send_email(
        to_email=request.to,
        subject="SpyderWash Notification",
        body=request.message,
    )
    return {"success": success}
