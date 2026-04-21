"""
SSE stream endpoints.

GET /api/stream/task/{job_id}
  Emits newline-delimited JSON events for job lifecycle:
    {"event": "queued",   "job_id": "...", "topic": "...",    "ts": "..."}
    {"event": "started",  "job_id": "...",                    "ts": "..."}
    {"event": "done",     "job_id": "...", "review_id": "...", "ts": "...", ...stats}
    {"event": "failed",   "job_id": "...", "error": "...",    "ts": "..."}
  Stream closes after "done" or "failed".

GET /api/stream/trace/{job_id}
  Emits one event per agent tool call:
    {"event": "step", "job_id": "...", "agent": "...", "tool": "...", ...}
  Replays all steps buffered before connection, then streams live events.
  Stream closes after the terminal task event arrives on the task channel.

Both use Server-Sent Events (text/event-stream) format:
  data: {json}\n\n
  : heartbeat\n\n   (every 15 s to keep proxies alive)
"""
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.stream_service import stream_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stream", tags=["stream"])

HEARTBEAT_INTERVAL = 15  # seconds
STREAM_TIMEOUT = 1800     # 30 min hard cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _new_pubsub(channel: str) -> tuple[aioredis.Redis, aioredis.client.PubSub]:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    ps = r.pubsub()
    await ps.subscribe(channel)
    return r, ps


async def _next_message(ps: aioredis.client.PubSub, timeout: float = 0.5) -> str | None:
    """Poll for a single message; returns the raw JSON string or None."""
    try:
        msg = await asyncio.wait_for(
            ps.get_message(ignore_subscribe_messages=True, timeout=timeout),
            timeout=timeout + 0.1,
        )
    except asyncio.TimeoutError:
        return None
    if msg and msg["type"] == "message":
        return msg["data"]
    return None


def _sse(data: str) -> str:
    return f"data: {data}\n\n"


def _heartbeat() -> str:
    return ": heartbeat\n\n"


# ---------------------------------------------------------------------------
# Task lifecycle stream
# ---------------------------------------------------------------------------

@router.get("/task/{job_id}")
async def stream_task(job_id: str):
    async def generator():
        # If the job already finished, return cached final event immediately
        final = stream_service.get_task_final(job_id)
        if final:
            yield _sse(final)
            return

        r, ps = await _new_pubsub(f"task:{job_id}")
        deadline = asyncio.get_event_loop().time() + STREAM_TIMEOUT
        last_hb = asyncio.get_event_loop().time()

        try:
            while asyncio.get_event_loop().time() < deadline:
                raw = await _next_message(ps)

                now = asyncio.get_event_loop().time()
                if now - last_hb >= HEARTBEAT_INTERVAL:
                    yield _heartbeat()
                    last_hb = now

                if raw is None:
                    continue

                yield _sse(raw)

                try:
                    event_type = json.loads(raw).get("event")
                except (json.JSONDecodeError, AttributeError):
                    event_type = None

                if event_type in ("done", "failed"):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await ps.unsubscribe()
            await r.aclose()

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ---------------------------------------------------------------------------
# Trace step stream
# ---------------------------------------------------------------------------

@router.get("/trace/{job_id}")
async def stream_trace(job_id: str):
    async def generator():
        # Replay steps that arrived before the client connected
        for raw in stream_service.get_buffered_steps(job_id):
            yield _sse(raw)

        # Check if already done; if so nothing more to stream
        final = stream_service.get_task_final(job_id)
        if final:
            return

        # Subscribe to both channels:
        #   trace:{job_id}  — new steps
        #   task:{job_id}   — terminal event signals end-of-stream
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        ps = r.pubsub()
        await ps.subscribe(f"trace:{job_id}", f"task:{job_id}")

        deadline = asyncio.get_event_loop().time() + STREAM_TIMEOUT
        last_hb = asyncio.get_event_loop().time()

        try:
            while asyncio.get_event_loop().time() < deadline:
                raw = await _next_message(ps)

                now = asyncio.get_event_loop().time()
                if now - last_hb >= HEARTBEAT_INTERVAL:
                    yield _heartbeat()
                    last_hb = now

                if raw is None:
                    continue

                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                event_type = parsed.get("event")

                if event_type == "step":
                    yield _sse(raw)
                elif event_type in ("done", "failed"):
                    # Terminal — no more steps will come
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await ps.unsubscribe()
            await r.aclose()

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
