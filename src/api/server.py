"""
Production FastAPI server exposing the LangGraph agent as a REST endpoint.

Intended consumer: .NET frontend at beta.spyderwash.com.

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
from fastapi import Depends
from src.utils.security import verify_api_key   
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

# Import the compiled LangGraph state machine (singleton, created at module load).
from src.agent.graph import agent_app as compiled_graph
from src.utils.security import sanitize_user_text
from src.voice_gateway.twilio_routes import router as twilio_router
from src.voice_gateway.websocket import router as websocket_router

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------

# Use a named logger so output can be routed independently in production
# (e.g. shipped to Datadog, CloudWatch, or Loki via a logging handler).
logger = logging.getLogger("setomatic.api")

# Emit ISO-8601 timestamps, log level, and message — one line per event.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  |  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    # operator_id scopes the request to a specific operator account.
    operator_id: int = Field(..., description="Numeric operator account ID.")
    # session_id is passed directly to LangGraph as the thread_id so that
    # MemorySaver can resume multi-turn conversation context on every call.
    session_id: str  = Field(..., description="Stable session identifier for conversation memory.")
    message: str     = Field(..., description="The operator's plain-text message.")
    operator_name: Optional[str] = Field(None, description="Operator display name for escalation emails.")
    operator_email: Optional[str] = Field(None, description="Operator email for escalation emails.")
    operator_phone: Optional[str] = Field(None, description="Operator phone for escalation emails.")
    channel: str = Field(default="chat", description="chat | voice")


class ChatResponse(BaseModel):
    # reply is the final natural-language answer produced by the agent.
    reply: str                = Field(..., description="Final AI-generated reply.")
    # detected_intent is the semantic category assigned by the router node.
    detected_intent: str      = Field(..., description="Intent label from the router classifier.")
    # requires_escalation is True when the escalation node fired (store down / human requested).
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

app.include_router(twilio_router)
app.include_router(websocket_router)

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


def run_agent(
    operator_id: int,
    session_id: str,
    message: str,
    channel: str = "chat",
    operator_name: Optional[str] = None,
    operator_email: Optional[str] = None,
    operator_phone: Optional[str] = None,
) -> dict:
    """
    Core agent invocation, shared by the HTTP route below and by the voice
    websocket gateway (src/voice_gateway/agent_client.py), which imports this
    function lazily (inside its ask() method) to avoid a circular import,
    since websocket.py is itself imported by this module above.

    This is synchronous/blocking — compiled_graph.invoke() is not async.
    Callers running on an asyncio event loop (the websocket handler) must
    wrap this in asyncio.to_thread(...) or it will stall the loop.
    """
    config = {"configurable": {"thread_id": session_id}}
    safe_message = sanitize_user_text(message)

    initial_state: dict = {
        "messages": [("user", safe_message)],
        "operator_id": operator_id,
        "channel": channel,
    }
    logger.info(f"[GRAPH] Initial State Channel: {initial_state['channel']}")

    if operator_name:
        initial_state["operator_name"] = operator_name
    if operator_email:
        initial_state["operator_email"] = operator_email
    if operator_phone:
        initial_state["operator_phone"] = operator_phone

    final_state: dict = compiled_graph.invoke(initial_state, config=config)

    return {
        "reply": _extract_reply(final_state),
        "detected_intent": final_state.get("current_intent") or "unknown",
        "requires_escalation": bool(final_state.get("escalation_dispatched", False)),
    }

# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
app.mount('/static',StaticFiles(directory='static'),name='static')
templates=Jinja2Templates(directory='templates')

@app.on_event("startup")
async def startup():
    print("Setomatic Operator AI started.")
    try:
        from src.services.images.ensure import ensure_images_extracted
        ensure_images_extracted("all")
    except Exception as exc:
        logger.warning("[STARTUP] Image extract bootstrap failed: %s", exc)

@app.get('/index')
def home(request:Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )

@app.post("/api/v1/agent/chat", response_model=ChatResponse)
def chat(request: ChatRequest, _: None = Depends(verify_api_key)) -> ChatResponse:
    """
    Accept an operator message, run it through the LangGraph state machine,
    and return a structured response containing the reply, the detected intent,
    and whether an escalation was triggered.

    Thread memory is keyed on session_id so multi-turn context is preserved
    across consecutive calls from the same operator session.
    """
    try:
        result = run_agent(
            operator_id=request.operator_id,
            session_id=request.session_id,
            message=request.message,
            channel=request.channel,
            operator_name=request.operator_name,
            operator_email=request.operator_email,
            operator_phone=request.operator_phone,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Graph execution failed: {exc}",
        )

    return ChatResponse(**result)


# ---------------------------------------------------------------------------
# MCP Knowledge Base Tools (structured retrieval for external agents)
# ---------------------------------------------------------------------------

from src.services.kb_mcp_tools import (
    KBSearchInput,
    KBGetArticleInput,
    KBGetCompanionsInput,
    kb_search,
    kb_get_article,
    kb_get_companions,
    kb_diagnostics,
)


@app.post("/api/v1/kb/search")
def api_kb_search(input: KBSearchInput):
    """Search the knowledge base by query text, intent, and device type."""
    return kb_search(input)


@app.get("/api/v1/kb/article/{article_id}")
def api_kb_get_article(article_id: str):
    """Retrieve a specific KB article by its ID."""
    result = kb_get_article(KBGetArticleInput(article_id=article_id))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found")
    return result


@app.get("/api/v1/kb/companions/{article_id}")
def api_kb_get_companions(article_id: str):
    """Get all co-retrieval companion articles for a given article."""
    return kb_get_companions(KBGetCompanionsInput(article_id=article_id))


@app.get("/api/v1/kb/diagnostics")
def api_kb_diagnostics():
    """Get KB retrieval system health and statistics, including monitoring metrics."""
    from src.services.kb_database import get_retrieval_diagnostics_24h
    base = kb_diagnostics()
    monitoring = get_retrieval_diagnostics_24h()
    if isinstance(base, dict):
        base["monitoring_24h"] = monitoring
        return base
    return {"diagnostics": base, "monitoring_24h": monitoring}


# ---------------------------------------------------------------------------
# Image Retrieval API (KB visual assets)
# ---------------------------------------------------------------------------

from src.services.image_retrieval import (
    get_case_images,
    search_case_images,
    get_case_visual_bundle,
)


class ImageSearchInput(BaseModel):
    query: str = Field(..., description="Search query for image terms")
    device: str = Field(default="", description="Optional device filter")
    image_type: str = Field(default="", description="Optional image type filter")
    limit: int = Field(default=12, description="Max results")


@app.get("/api/v1/kb/images/{article_id}")
def api_get_case_images(article_id: str, include_linked: bool = True, limit: int = 12):
    """Get images for a case ID, optionally including linked-case images."""
    results = get_case_images(article_id, include_linked=include_linked, limit=limit)
    if not results:
        raise HTTPException(status_code=404, detail=f"No images found for {article_id}")
    return {"article_id": article_id, "images": results, "total": len(results)}


@app.post("/api/v1/kb/images/search")
def api_search_case_images(input: ImageSearchInput):
    """Search images by query terms, device, and type."""
    results = search_case_images(
        query=input.query, device=input.device,
        image_type=input.image_type, limit=input.limit,
    )
    return {"results": results, "total": len(results)}


@app.get("/api/v1/kb/images/bundle/{article_id}")
def api_get_visual_bundle(article_id: str):
    """Get the full visual bundle: article + images (primary + companions)."""
    bundle = get_case_visual_bundle(article_id)
    if not bundle.get("article"):
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found")
    return bundle


# Static mount for serving extracted images
import os
from fastapi.staticfiles import StaticFiles

_kb_images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "kb_images")
_kb_images_dir = os.path.normpath(_kb_images_dir)
if os.path.isdir(_kb_images_dir):
    app.mount("/kb_images", StaticFiles(directory=_kb_images_dir), name="kb_images")


# ---------------------------------------------------------------------------
# Health check (useful for load-balancer / k8s liveness probes)
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Lightweight liveness probe — returns 200 if the process is alive."""
    return {"status": "healthy", "service": "setomatic-operator-ai"}
