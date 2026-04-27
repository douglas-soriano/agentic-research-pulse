"""
LangSmith trace helpers.

Provides agent_trace() — a context manager that creates a named span
in LangSmith when LANGCHAIN_TRACING_V2=true, and is a no-op otherwise.
The parent-child span hierarchy is managed automatically via Python contextvars:
any @traceable call or wrap_openai LLM call made inside an agent_trace block
becomes a child span.
"""
from contextlib import contextmanager, nullcontext
from typing import Any


@contextmanager
def agent_trace(name: str, run_type: str = "chain", **inputs: Any):
    """
    Create a LangSmith span if tracing is enabled.
    Usage:
        with agent_trace("pipeline_run", job_id=job_id, topic=topic):
            ...
    """
    try:
        from langsmith import trace
        with trace(name=name, run_type=run_type, inputs=inputs):
            yield
    except Exception:
        # If langsmith is misconfigured or unavailable, never crash the pipeline.
        yield
