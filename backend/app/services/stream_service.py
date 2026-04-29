import json
from datetime import datetime, timezone

import redis as sync_redis

from app.config import settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StreamService:

    _client: sync_redis.Redis | None = None

    def _r(self) -> sync_redis.Redis:
        if self._client is None:
            self._client = sync_redis.from_url(settings.redis_url, decode_responses=True)
        return self._client


    def task_queued(self, job_id: str, topic: str) -> None:
        self._publish_task(job_id, {"event": "queued", "job_id": job_id, "topic": topic, "ts": _utc_now()})

    def task_started(self, job_id: str) -> None:
        self._publish_task(job_id, {"event": "started", "job_id": job_id, "ts": _utc_now()})

    def task_done(self, job_id: str, review_id: str, stats: dict) -> None:
        payload = {"event": "done", "job_id": job_id, "review_id": review_id, "ts": _utc_now(), **stats}
        self._publish_task(job_id, payload)

        self._r().setex(f"task_final:{job_id}", 3600, json.dumps(payload))

    def task_failed(self, job_id: str, error: str) -> None:
        payload = {"event": "failed", "job_id": job_id, "error": error, "ts": _utc_now()}
        self._publish_task(job_id, payload)
        self._r().setex(f"task_final:{job_id}", 3600, json.dumps(payload))

    def _publish_task(self, job_id: str, payload: dict) -> None:
        self._r().publish(f"task:{job_id}", json.dumps(payload))


    def trace_step(self, job_id: str, step: dict) -> None:
        raw = json.dumps({"event": "step", "job_id": job_id, **step})
        pipe = self._r().pipeline()
        pipe.rpush(f"trace_steps:{job_id}", raw)
        pipe.expire(f"trace_steps:{job_id}", 3600)
        pipe.publish(f"trace:{job_id}", raw)
        pipe.execute()

    def get_buffered_steps(self, job_id: str) -> list[str]:
        return self._r().lrange(f"trace_steps:{job_id}", 0, -1)

    def get_task_final(self, job_id: str) -> str | None:
        return self._r().get(f"task_final:{job_id}")


stream_service = StreamService()
