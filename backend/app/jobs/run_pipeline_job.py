"""
run_pipeline_job — the main async job triggered when a topic is added.
Runs the full multi-agent orchestration pipeline.
"""
import structlog
from openai import APIStatusError

from celery_worker import celery_app
from app.agents.orchestrator import Orchestrator

logger = structlog.get_logger(__name__)


def _retryable_pipeline_error(exc: BaseException) -> bool:
    """Retry only on true transient infrastructure failures (5xx).
    LLM 429s (rate limit or quota) are handled gracefully inside each agent."""
    if isinstance(exc, APIStatusError):
        return exc.status_code in (500, 503)
    text = str(exc).lower()
    return "503" in text or "service unavailable" in text


@celery_app.task(
    name="jobs.run_pipeline",
    bind=True,
    max_retries=4,
    default_retry_delay=90,
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1500,
)
def run_pipeline(self, job_id: str, topic_id: str, topic_name: str, max_papers: int = 8) -> dict:
    # Bind job context to every log entry produced during this task.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(job_id=job_id, topic=topic_name)

    logger.info("task_started", job_id=job_id, topic=topic_name, step="start")

    try:
        orchestrator = Orchestrator(job_id=job_id)
        result = orchestrator.run(topic_id=topic_id, topic_name=topic_name, max_papers=max_papers)
        logger.info("task_completed", job_id=job_id, **{k: v for k, v in result.items() if k != "review_id"})
        return result
    except Exception as exc:
        if not _retryable_pipeline_error(exc):
            logger.error("task_failed_non_retryable", job_id=job_id, error=str(exc), step="run_pipeline")
            raise
        countdown = min(90 * (2 ** self.request.retries), 600)
        logger.warning(
            "task_retrying",
            job_id=job_id,
            error=str(exc),
            attempt=self.request.retries,
            countdown_s=countdown,
            step="run_pipeline",
        )
        raise self.retry(exc=exc, countdown=countdown)
