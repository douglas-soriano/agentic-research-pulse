from contextlib import contextmanager, nullcontext
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@contextmanager
def agent_trace(name: str, run_type: str = "chain", **inputs: Any):
    try:
        from langsmith import trace
        with trace(name=name, run_type=run_type, inputs=inputs):
            yield
    except ImportError as exc:
        logger.info("langsmith_unavailable", error=str(exc), trace_name=name)
        yield
