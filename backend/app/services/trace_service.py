"""
TraceService — records every agent tool call for observability and
publishes each step to the real-time SSE stream via StreamService.
"""
import time
from contextlib import contextmanager
from datetime import datetime

from app.database import get_session
from app.models.trace import Trace, TraceCreate, TraceStep
from app.repositories.trace_repository import TraceRepository
from app.services.stream_service import stream_service


class TraceService:
    def start(self, job_id: str, topic: str) -> Trace:
        with get_session() as session:
            repo = TraceRepository(session)
            return repo.create(TraceCreate(job_id=job_id, topic=topic))

    def record_step(
        self,
        job_id: str,
        agent: str,
        tool: str | None,
        input_data: dict,
        output_data: dict,
        duration_ms: int,
        success: bool,
        error: str | None = None,
    ) -> None:
        step = TraceStep(
            agent=agent,
            tool=tool,
            input=input_data,
            output=output_data,
            duration_ms=duration_ms,
            success=success,
            error=error,
        )
        with get_session() as session:
            repo = TraceRepository(session)
            repo.append_step(job_id, step)

        # Publish to SSE stream in real time
        try:
            stream_service.trace_step(job_id, step.model_dump(mode="json"))
        except Exception:
            pass  # Stream publish failure must never crash the agent

    def complete(self, job_id: str, stats: dict) -> None:
        with get_session() as session:
            repo = TraceRepository(session)
            repo.complete(job_id, stats)

    def fail(self, job_id: str, error: str) -> None:
        with get_session() as session:
            repo = TraceRepository(session)
            repo.fail(job_id, error)

    def get(self, job_id: str) -> Trace | None:
        with get_session() as session:
            repo = TraceRepository(session)
            return repo.get_by_job_id(job_id)

    def list_recent(self, limit: int = 20) -> list[Trace]:
        with get_session() as session:
            repo = TraceRepository(session)
            return repo.list_recent(limit)

    @contextmanager
    def timed_tool(self, job_id: str, agent: str, tool: str, input_data: dict):
        start = time.monotonic()
        output: dict = {}
        success = True
        error = None
        try:
            yield output
        except Exception as e:
            success = False
            error = str(e)
            output["error"] = str(e)
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            self.record_step(
                job_id=job_id,
                agent=agent,
                tool=tool,
                input_data=input_data,
                output_data=output,
                duration_ms=duration_ms,
                success=success,
                error=error,
            )
