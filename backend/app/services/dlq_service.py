"""
Dead Letter Queue backed by Redis.

Failed jobs are stored as:
  researchpulse:dlq:entry:{job_id}  → hash  (job_id, error_message, failed_at, attempt_count, payload)
  researchpulse:dlq:index           → sorted set (score=unix_ts, member=job_id)
"""
import json
import time
from datetime import datetime, timezone

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

_ENTRY_PREFIX = "researchpulse:dlq:entry:"
_INDEX_KEY = "researchpulse:dlq:index"


def _redis():
    import redis
    return redis.from_url(settings.redis_url, decode_responses=True)


class DlqService:
    def push(
        self,
        job_id: str,
        error_message: str,
        original_payload: dict,
        attempt_count: int,
    ) -> None:
        entry = {
            "job_id": job_id,
            "error_message": str(error_message)[:1000],
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "attempt_count": str(attempt_count),
            "payload": json.dumps(original_payload),
        }
        try:
            r = _redis()
            r.hset(f"{_ENTRY_PREFIX}{job_id}", mapping=entry)
            r.zadd(_INDEX_KEY, {job_id: time.time()})
            logger.warning(
                "dlq_entry_added",
                job_id=job_id,
                attempt_count=attempt_count,
                error=error_message[:200],
            )
        except Exception as exc:
            logger.error("dlq_push_failed", job_id=job_id, error=str(exc))

    def list_entries(self, limit: int = 50) -> list[dict]:
        try:
            r = _redis()
            job_ids = r.zrevrange(_INDEX_KEY, 0, limit - 1)
            entries = []
            for job_id in job_ids:
                data = r.hgetall(f"{_ENTRY_PREFIX}{job_id}")
                if data:
                    entries.append(_parse_entry(data))
            return entries
        except Exception as exc:
            logger.error("dlq_list_failed", error=str(exc))
            return []

    def get_entry(self, job_id: str) -> dict | None:
        try:
            r = _redis()
            data = r.hgetall(f"{_ENTRY_PREFIX}{job_id}")
            if not data:
                return None
            return _parse_entry(data)
        except Exception as exc:
            logger.error("dlq_get_failed", job_id=job_id, error=str(exc))
            return None

    def remove(self, job_id: str) -> None:
        try:
            r = _redis()
            r.delete(f"{_ENTRY_PREFIX}{job_id}")
            r.zrem(_INDEX_KEY, job_id)
        except Exception as exc:
            logger.error("dlq_remove_failed", job_id=job_id, error=str(exc))

    def count(self) -> int:
        try:
            return _redis().zcard(_INDEX_KEY) or 0
        except Exception:
            return 0


def _parse_entry(data: dict) -> dict:
    entry = dict(data)
    entry["attempt_count"] = int(entry.get("attempt_count", 0))
    raw_payload = entry.pop("payload", "{}")
    try:
        entry["original_payload"] = json.loads(raw_payload)
    except Exception:
        entry["original_payload"] = {}
    return entry


dlq_service = DlqService()
