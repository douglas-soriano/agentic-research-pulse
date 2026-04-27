"""
Redis-backed circuit breaker for LLM provider calls.

States:
  CLOSED    — normal operation
  OPEN      — failing fast; no requests allowed
  HALF_OPEN — one test request allowed; success closes, failure reopens

Thresholds:
  3 failures in 30 s → OPEN
  OPEN for 60 s → HALF_OPEN
  HALF_OPEN + success → CLOSED
"""
import time
import uuid

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"

FAILURE_THRESHOLD = 3
FAILURE_WINDOW_S = 30
RECOVERY_TIMEOUT_S = 60


def _get_redis():
    import redis
    return redis.from_url(settings.redis_url, decode_responses=True)


class CircuitBreaker:
    def __init__(self, provider_name: str):
        self.name = provider_name
        self._state_key = f"researchpulse:circuit:{provider_name}"
        self._failures_key = f"researchpulse:circuit:{provider_name}:failures"

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _get_raw_state(self) -> tuple[str, float]:
        """Return (state_str, opened_at_timestamp)."""
        try:
            r = _get_redis()
            data = r.hgetall(self._state_key)
            if not data:
                return CLOSED, 0.0
            return data.get("state", CLOSED), float(data.get("opened_at", 0))
        except Exception:
            return CLOSED, 0.0

    @property
    def state(self) -> str:
        state, opened_at = self._get_raw_state()
        if state == OPEN and time.time() - opened_at >= RECOVERY_TIMEOUT_S:
            self._transition(HALF_OPEN, opened_at)
            return HALF_OPEN
        return state

    def _transition(self, new_state: str, opened_at: float | None = None) -> None:
        try:
            old_state, prev_opened_at = self._get_raw_state()
            if old_state == new_state:
                return
            if opened_at is None:
                opened_at = time.time()
            r = _get_redis()
            r.hset(self._state_key, mapping={
                "state": new_state,
                "opened_at": str(opened_at),
            })
            logger.warning(
                "circuit_breaker_state_change",
                provider=self.name,
                from_state=old_state,
                to_state=new_state,
            )
        except Exception as exc:
            logger.warning("circuit_breaker_redis_error", error=str(exc), provider=self.name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow_request(self) -> bool:
        state = self.state
        if state in (CLOSED, HALF_OPEN):
            return True
        logger.warning("circuit_breaker_open_reject", provider=self.name)
        return False

    def record_success(self) -> None:
        state = self.state
        if state == HALF_OPEN:
            try:
                _get_redis().delete(self._failures_key)
            except Exception:
                pass
            self._transition(CLOSED)

    def record_failure(self) -> None:
        now = time.time()
        try:
            r = _get_redis()
            pipe = r.pipeline()
            pipe.zadd(self._failures_key, {str(uuid.uuid4()): now})
            pipe.zremrangebyscore(self._failures_key, 0, now - FAILURE_WINDOW_S)
            pipe.zcard(self._failures_key)
            results = pipe.execute()
            failure_count = results[2]
        except Exception as exc:
            logger.warning("circuit_breaker_redis_error", error=str(exc))
            return

        current = self.state
        if failure_count >= FAILURE_THRESHOLD and current in (CLOSED, HALF_OPEN):
            self._transition(OPEN)
            logger.warning(
                "circuit_breaker_opened",
                provider=self.name,
                failure_count=failure_count,
                window_s=FAILURE_WINDOW_S,
            )


class CircuitOpenError(RuntimeError):
    """Raised when all LLM providers have open circuits."""


# Module-level registry — one CB instance per provider, reused across calls.
_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(provider_name: str) -> CircuitBreaker:
    if provider_name not in _breakers:
        _breakers[provider_name] = CircuitBreaker(provider_name)
    return _breakers[provider_name]
