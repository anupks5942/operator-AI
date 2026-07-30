import asyncio
import logging
from src.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


class AgentClient:
    async def ask(self, operator_id: int, session_id: str, message: str):
        """
        Calls the LangGraph agent in-process via src.api.server.run_agent().

        The import is deferred to call time (not module load time) to avoid
        a circular import: server.py imports websocket_router at startup,
        which imports this module — so this module can't import server.py
        at the top level. By the time ask() actually runs, server.py has
        long finished loading, so the import resolves cleanly.

        run_agent() is sync/blocking, so it's offloaded to a worker thread
        to keep the event loop free for other calls and for interrupts.
        """
        from src.api.server import run_agent

        try:
            return await asyncio.to_thread(
                run_agent,
                operator_id=operator_id,
                session_id=session_id,
                message=message,
                channel="voice",
            )
        except Exception:
            logger.exception("Failed to run Operator Agent graph")
            return {
                "reply": (
                    "I'm sorry. I'm currently unable to access the "
                    "support system. Please try again in a few moments."
                )
            }


agent = AgentClient()