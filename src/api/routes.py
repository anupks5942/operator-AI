from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from src.api.schemas import QueryRequest, QueryResponse, NotificationRequest
from src.agent.graph import agent_app
from src.services.notifications import NotificationService

router = APIRouter()

@router.get("/health")
def health_check():
    return {"status": "healthy"}

@router.post("/query", response_model=QueryResponse)
def query_agent(request: QueryRequest):
    """
    Endpoint to query the Setomatic technical support agent.
    """
    try:
        # Initialize state with the user's message
        initial_state = {
            "messages": [HumanMessage(content=request.query)],
            "context": ""
        }
        
        # Invoke LangGraph agent
        final_state = agent_app.invoke(initial_state)
        
        # Extract the final answer
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
    success = NotificationService.send_sms(to_number=request.to, message=request.message)
    return {"success": success}

@router.post("/notify/email")
def notify_email(request: NotificationRequest):
    success = NotificationService.send_email(
        to_email=request.to,
        subject="SpyderWash Notification",
        body=request.message,
    )
    return {"success": success}
