import asyncio
import re
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .agent_client import agent
from .formatter import format_for_voice
import logging
from src.logging_config import setup_logging
import random

setup_logging()

logger = logging.getLogger(__name__)
router = APIRouter()

FILLER_INTERVALS = [2.0, 5.0, 6.0, 7.0]

EARLY_FILLERS = [
    "One moment, let me check that.",
    "Give me just a second.",
    "Let me look into that for you.",
    "One second, pulling that up.",
    "Just a moment, checking now.",
    "Let me take a quick look.",
]

LATER_FILLERS = [
    "Still working on that for you.",
    "Thanks for your patience, almost there.",
    "Still checking, one more moment.",
    "Just a little longer, bear with me.",
]

HANGUP_PATTERNS = re.compile(
    r"\b(bye|goodbye|good bye|that'?s all|hang up|end the call|talk to you later)\b",
    re.IGNORECASE,
)

# How long a caller is allowed to pause mid-thought before we treat their
# speech fragments as separate, complete queries.
PAUSE_MERGE_WINDOW = 1.0  # seconds


def estimate_speech_seconds(text: str) -> float:
    """Rough estimate of TTS playback duration based on word count (~150 wpm)."""
    words = len(text.split())
    return max(1.5, (words / 150) * 60)


@router.websocket("/ws")
async def conversation(ws: WebSocket):
    await ws.accept()
    call_sid = None
    operator_id = 4

    current_task: asyncio.Task | None = None
    merge_task: asyncio.Task | None = None
    pending_prompt_parts: list[str] = []
    generation = 0  # bumps every time a new prompt/interrupt invalidates in-flight work

    async def send_text(token: str, last: bool = True, **extra):
        await ws.send_json({"type": "text", "token": token, "last": last, **extra})

    async def keep_caller_engaged(my_generation: int):
        """
        Runs alongside a slow agent call, sending short check-ins at
        increasing intervals so the caller never sits in dead air.
        Cancelled automatically the moment the real answer is ready.
        """
        used = set()

        def pick(pool):
            available = [p for p in pool if p not in used] or pool
            choice = random.choice(available)
            used.add(choice)
            return choice

        stage = 0
        try:
            for delay in FILLER_INTERVALS:
                await asyncio.sleep(delay)
                if my_generation != generation:
                    return  # superseded — stop engaging silently
                pool = EARLY_FILLERS if stage == 0 else LATER_FILLERS
                filler = pick(pool)
                await send_text(filler, last=False, interruptible=True, preemptible=True)
                stage += 1
        except asyncio.CancelledError:
            # Normal path: the real response arrived before the next check-in fired.
            raise

    async def schedule_merged_prompt(my_generation: int):
        """
        Waits briefly to see if the caller keeps talking (a paused thought)
        before dispatching the accumulated text to the agent. If a newer
        fragment arrives, this task is cancelled and the newer one's own
        timer takes over — so only the last fragment's wait actually fires.
        """
        nonlocal current_task
        try:
            await asyncio.sleep(PAUSE_MERGE_WINDOW)
        except asyncio.CancelledError:
            return  # superseded by a newer fragment; that task will dispatch instead

        if my_generation != generation:
            return

        merged_text = " ".join(p.strip() for p in pending_prompt_parts if p.strip())
        pending_prompt_parts.clear()
        if not merged_text:
            return

        current_task = asyncio.create_task(handle_prompt(merged_text, my_generation))

    async def handle_prompt(voice_prompt: str, my_generation: int):
        engagement_task = asyncio.create_task(keep_caller_engaged(my_generation))
        try:
            response = await agent.ask(
                operator_id=operator_id,
                session_id=call_sid,
                message=voice_prompt,
            )

            if my_generation != generation:
                logger.info("Dropping stale response for generation %s (current=%s)", my_generation, generation)
                return

            logger.info(f"[AI] {response['reply']}")
            reply_text = response["reply"]

            if HANGUP_PATTERNS.search(voice_prompt):
                spoken = format_for_voice(reply_text)

                try:
                    await send_text(spoken, last=True)
                    await ws.send_json({"type": "end", "handoffData": '{"reason": "caller ended conversation"}'})
                except Exception:
                    logger.info("Socket already closing during goodbye send; skipping hold.")
                    return

                # Hold the connection open long enough for TTS to finish speaking
                # the goodbye. If the caller speaks again before this elapses
                # (new prompt/interrupt bumps `generation`), abandon the hold
                # quietly — the caller has already moved on, so there's no
                # error to report and no goodbye left to protect.
                try:
                    await asyncio.sleep(estimate_speech_seconds(spoken))
                except asyncio.CancelledError:
                    logger.info(
                        "Goodbye hold cancelled for generation %s (caller spoke again).",
                        my_generation,
                    )
                    raise
                return

            await send_text(format_for_voice(reply_text), last=True)

        except asyncio.CancelledError:
            logger.info("Prompt processing cancelled (superseded by newer prompt/interrupt).")
            raise
        except Exception:
            logger.exception("Error while processing voice request.")
            if my_generation == generation:
                await send_text(
                    "I'm sorry. Something went wrong. Could you please repeat that?",
                    last=True,
                )
        finally:
            if not engagement_task.done():
                engagement_task.cancel()

    try:
        while True:
            event = await ws.receive_json()
            event_type = event.get("type")
            voice_prompt = event.get("voicePrompt")

            if event_type == "setup":
                call_sid = event["callSid"]
                logger.info("Operator %s connected. Call SID=%s", operator_id, call_sid)
                continue

            elif event_type == "prompt":
                logger.info(f"[VOICE] {voice_prompt}")
                if not call_sid or not voice_prompt:
                    continue

                pending_prompt_parts.append(voice_prompt)

                # A new fragment supersedes any answer currently being generated —
                # the caller is still talking, so nothing should be sent yet.
                # We don't dispatch immediately; instead we wait a short window
                # to see if this is a paused thought that continues, and merge
                # fragments that arrive within that window into one query.
                generation += 1
                if current_task and not current_task.done():
                    current_task.cancel()
                if merge_task and not merge_task.done():
                    merge_task.cancel()

                merge_task = asyncio.create_task(schedule_merged_prompt(generation))

            elif event_type == "interrupt":
                logger.info("Caller interrupted assistant: %s", event.get("utteranceUntilInterrupt"))
                # Invalidate whatever's in flight so its answer never gets sent
                # after the caller has already moved on.
                generation += 1
                if current_task and not current_task.done():
                    current_task.cancel()
                if merge_task and not merge_task.done():
                    merge_task.cancel()
                pending_prompt_parts.clear()
                continue

            elif event_type == "error":
                logger.error(event)
                continue

            else:
                logger.warning("Unknown ConversationRelay event: %s", event)

    except WebSocketDisconnect:
        logger.info("Call disconnected")
    finally:
        if current_task and not current_task.done():
            current_task.cancel()
        if merge_task and not merge_task.done():
            merge_task.cancel()