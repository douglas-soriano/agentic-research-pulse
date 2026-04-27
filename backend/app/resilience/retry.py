"""
Reusable tenacity retry decorators for external HTTP calls.

Non-retryable (fail immediately): 400, 401, 403, 404
Retryable (backoff 1s → 2s → 4s): 429, 500, 502, 503, 504, network timeout
"""
import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = structlog.get_logger(__name__)

_NON_RETRYABLE_STATUS = {400, 401, 403, 404}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    # Network-level errors (connection refused, DNS failure, etc.)
    if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    return False


def _is_non_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _NON_RETRYABLE_STATUS
    return False


# Standard retry decorator: up to 3 retries (4 total attempts), backoff 1s→2s→4s
http_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
