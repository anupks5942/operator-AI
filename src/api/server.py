"""
Production API for the Operator AI.

.NET and React call this server. Main endpoint: POST /api/v1/agent/chat

Run:
    uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
"""
import logging
import time
import uuid
from datetime import datetime, timezone

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from dotenv import load_dotenv

load_dotenv()

# Ready-made chat graph (shared for the whole process).
from src.agent.graph import agent_app as compiled_graph
from src.utils.security import sanitize_user_text

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------

# Named logger so production can ship these logs to monitoring tools.
logger = logging.getLogger("setomatic.api")

# One-line log format with time and level.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  |  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """What the frontend sends for one chat turn."""

    # Operator account number (shown on tickets; tools still use OperatorId=4 today).
    operator_id: int = Field(..., description="Numeric operator account ID.")
    # Same id on every message keeps the chat memory for that conversation.
    session_id: str  = Field(..., description="Stable session identifier for conversation memory.")
    message: str     = Field(..., description="The operator's plain-text message.")
    operator_name: Optional[str] = Field(None, description="Operator display name for escalation emails.")
    operator_email: Optional[str] = Field(None, description="Operator email for escalation emails.")
    operator_phone: Optional[str] = Field(None, description="Operator phone for escalation emails.")


class ChatResponse(BaseModel):
    """What we send back after one chat turn."""

    reply: str                = Field(..., description="Final AI-generated reply.")
    detected_intent: str      = Field(..., description="Intent label from the router classifier.")
    # True only if we actually sent a ticket this turn.
    requires_escalation: bool = Field(..., description="True if an SMS escalation was triggered.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Setomatic SpyderWash Operator AI — Production API",
    description="LangGraph-powered technical support agent endpoint for operator frontends.",
    version="1.0.0",
)

# CORS: allow the .NET frontend origin so browsers do not reject pre-flight requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://beta.spyderwash.com",
        "https://www.spyderwash.com",
        # Allow localhost during local .NET frontend development.
        "http://localhost:3000",
        "http://localhost:5000",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Telemetry middleware
# ---------------------------------------------------------------------------

# Paths that should be measured and logged — health probes are excluded to
# avoid flooding the log with noise from load-balancer liveness checks.
_MONITORED_PATHS = {"/api/v1/agent/chat"}

@app.middleware("http")
async def telemetry_middleware(request: Request, call_next) -> Response:
    """
    Intercepts every HTTP request, measures wall-clock latency, and emits a
    structured log line on both ingress and egress.

    Only requests matching _MONITORED_PATHS receive the full telemetry block;
    all other paths receive lightweight pass-through logging so the log
    stays actionable and free of health-probe clutter.
    """
    # Assign a short correlation ID so request/response pairs can be matched
    # across distributed log lines without scanning timestamps.
    correlation_id = uuid.uuid4().hex[:12]

    method  = request.method
    path    = request.url.path
    # Capture query string for debugging (e.g. ?operator_id=4 forwarded by proxy).
    qs      = f"?{request.url.query}" if request.url.query else ""
    full_url = f"{path}{qs}"

    # Record the monotonic start time for sub-millisecond accuracy.
    start_time = time.monotonic()

    # Log the incoming request before any processing begins.
    if path in _MONITORED_PATHS:
        logger.info(
            "[%s] --> %s %s  (client: %s)",
            correlation_id,
            method,
            full_url,
            request.client.host if request.client else "unknown",
        )
    else:
        # Minimal log for non-monitored paths (health, docs, openapi).
        logger.debug("[%s] --> %s %s", correlation_id, method, full_url)

    # Await the downstream route handler (or the next middleware in the stack).
    # Any exception raised inside the route will propagate naturally.
    response: Response = await call_next(request)

    # Calculate elapsed wall time in milliseconds with 2 decimal places.
    elapsed_ms = (time.monotonic() - start_time) * 1_000
    status_code = response.status_code

    # Classify the outcome so log scanners can filter on a single keyword
    # without parsing the numeric HTTP status code.
    if status_code < 400:
        outcome = "SUCCESS"
    elif status_code < 500:
        outcome = "CLIENT_ERROR"
    else:
        outcome = "SERVER_ERROR"

    if path in _MONITORED_PATHS:
        # Full telemetry block for monitored endpoints — includes all fields
        # needed for latency dashboards and SLA alerting.
        logger.info(
            "[%s] <-- %s %s  status=%d  outcome=%s  latency=%.2f ms",
            correlation_id,
            method,
            full_url,
            status_code,
            outcome,
            elapsed_ms,
        )

        # Emit a separate WARNING when latency breaches the 10-second threshold
        # so on-call engineers are notified without scanning individual log lines.
        if elapsed_ms > 10_000:
            logger.warning(
                "[%s] SLOW REQUEST  %s %s  latency=%.2f ms  (threshold: 10000 ms)",
                correlation_id,
                method,
                full_url,
                elapsed_ms,
            )

        # Emit a WARNING on server-side errors so failures are surfaced
        # immediately without requiring a separate error-rate query.
        if status_code >= 500:
            logger.warning(
                "[%s] SERVER ERROR  %s %s  status=%d",
                correlation_id,
                method,
                full_url,
                status_code,
            )
    else:
        logger.debug(
            "[%s] <-- %s %s  status=%d  latency=%.2f ms",
            correlation_id, method, full_url, status_code, elapsed_ms,
        )

    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_reply(graph_state: dict) -> str:
    """
    Walk backwards through the message list to find the last AIMessage that
    contains actual text content.  The ReAct tool loop can leave empty-content
    AIMessage objects (tool-call placeholders) ahead of the real summary, so a
    naive messages[-1].content would return an empty string.
    """
    for msg in reversed(graph_state.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content and str(msg.content).strip():
            return str(msg.content).strip()
    return "The agent processed your request but did not produce a text response."


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@app.post("/api/v1/agent/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """
    Accept an operator message, run it through the LangGraph state machine,
    and return a structured response containing the reply, the detected intent,
    and whether an escalation was triggered.

    Thread memory is keyed on session_id so multi-turn context is preserved
    across consecutive calls from the same operator session.
    """
    # Build the LangGraph invocation config; thread_id selects the MemorySaver
    # checkpoint bucket, giving each operator session its own memory partition.
    config = {"configurable": {"thread_id": request.session_id}}

    # Apply PCI-DSS compliance redactor to mask credit cards before sending to LangGraph.
    safe_message = sanitize_user_text(request.message)

    # Wrap the message in the tuple format LangGraph's add_messages reducer expects.
    initial_state: dict = {
        "messages": [("user", safe_message)],
        "operator_id": request.operator_id,
    }
    if request.operator_name:
        initial_state["operator_name"] = request.operator_name
    if request.operator_email:
        initial_state["operator_email"] = request.operator_email
    if request.operator_phone:
        initial_state["operator_phone"] = request.operator_phone

    try:
        # invoke() blocks until the full graph has executed and returns the
        # final accumulated state dict (all nodes merged).
        final_state: dict = compiled_graph.invoke(initial_state, config=config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Graph execution failed: {exc}",
        )

    # Extract the plain-text reply from the message history.
    reply = _extract_reply(final_state)

    # detected_intent is written to state by the router node; fall back to
    # "unknown" if the router did not execute (should not happen in practice).
    detected_intent: str = final_state.get("current_intent") or "unknown"

    # True when escalation_node dispatched email/SMS this turn.
    requires_escalation: bool = bool(final_state.get("escalation_dispatched", False))

    return ChatResponse(
        reply=reply,
        detected_intent=detected_intent,
        requires_escalation=requires_escalation,
    )


# ---------------------------------------------------------------------------
# Health check (useful for load-balancer / k8s liveness probes)
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Lightweight liveness probe — returns 200 if the process is alive."""
    return {"status": "healthy", "service": "setomatic-operator-ai"}
