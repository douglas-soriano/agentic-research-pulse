import time
from contextlib import contextmanager
from datetime import datetime

import structlog

from app.database import get_session
from app.models.trace import Trace, TraceCreate, TraceStep
from app.repositories.trace_repository import TraceRepository
from app.services.stream_service import stream_service

logger = structlog.get_logger(__name__)


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
        token_count: int | None = None,
        cost_usd: float | None = None,
    ) -> None:
        step = TraceStep(
            agent=agent,
            tool=tool,
            input=input_data,
            output=output_data,
            duration_ms=duration_ms,
            success=success,
            error=error,
            token_count=token_count,
            cost_usd=cost_usd,
        )
        with get_session() as session:
            repo = TraceRepository(session)
            repo.append_step(job_id, step)

        try:
            stream_service.trace_step(job_id, step.model_dump(mode="json"))
        except Exception as exc:
            logger.warning("trace_stream_publish_failed", job_id=job_id, error=str(exc))

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

    def latest_job_ids(self, topic_names: list[str]) -> dict[str, str]:
        with get_session() as session:
            repo = TraceRepository(session)
            return repo.latest_job_ids_by_topic(topic_names)

    @contextmanager
    def timed_tool(
        self,
        job_id: str,
        agent: str,
        tool: str,
        input_data: dict,
        token_count: int | None = None,
        cost_usd: float | None = None,
    ):
        start = time.monotonic()
        output: dict = {}
        success = True
        error = None
        try:
            yield output
        except Exception as exc:
            success = False
            error = str(exc)
            output["error"] = str(exc)
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
                token_count=token_count,
                cost_usd=cost_usd,
            )
