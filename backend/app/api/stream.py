import asyncio
import json
import structlog

import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.constants import DEFAULT_STREAM_HEARTBEAT_SECONDS, DEFAULT_STREAM_TIMEOUT_SECONDS
from app.config import settings
from app.services.stream_service import stream_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/stream", tags=["stream"])

HEARTBEAT_INTERVAL = DEFAULT_STREAM_HEARTBEAT_SECONDS
STREAM_TIMEOUT = DEFAULT_STREAM_TIMEOUT_SECONDS


async def _new_pubsub(channel: str) -> tuple[aioredis.Redis, aioredis.client.PubSub]:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    ps = r.pubsub()
    await ps.subscribe(channel)
    return r, ps


async def _next_message(ps: aioredis.client.PubSub, timeout: float = 0.5) -> str | None:
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


def _sse(data: str, event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {data}\n\n"


def _heartbeat() -> str:
    return ": heartbeat\n\n"


@router.get("/task/{job_id}")
async def stream_task(job_id: str):
    async def generator():

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
            logger.info("task_stream_cancelled", job_id=job_id)
        finally:
            await ps.unsubscribe()
            await r.aclose()

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@router.get("/trace/{job_id}")
async def stream_trace(job_id: str, request: Request):

    last_id_header = request.headers.get("last-event-id")
    start_index = int(last_id_header) + 1 if last_id_header and last_id_header.isdigit() else 0

    async def generator():
        buffered = stream_service.get_buffered_steps(job_id)
        next_id = len(buffered)
        for i, raw in enumerate(buffered):
            if i < start_index:
                continue
            yield _sse(raw, event_id=i)


        final = stream_service.get_task_final(job_id)
        if final:
            return


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
                    yield _sse(raw, event_id=next_id)
                    next_id += 1
                elif event_type in ("done", "failed"):
                    break
        except asyncio.CancelledError:
            logger.info("trace_stream_cancelled", job_id=job_id)
        finally:
            await ps.unsubscribe()
            await r.aclose()

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
