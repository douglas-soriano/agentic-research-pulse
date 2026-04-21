"""
run_pipeline_job — the main async job triggered when a topic is added.
Runs the full multi-agent orchestration pipeline.
"""
from openai import APIStatusError

from celery_worker import celery_app
from app.agents.orchestrator import Orchestrator


def _retryable_pipeline_error(exc: BaseException) -> bool:
    """Only retry transient API / overload errors — not validation bugs or bad input."""
    if isinstance(exc, APIStatusError):
        return exc.status_code in (429, 500, 503)
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "503" in text


@celery_app.task(
    name="jobs.run_pipeline",
    bind=True,
    max_retries=4,
    default_retry_delay=90,
    acks_late=True,
    time_limit=1800,  # 30 min hard limit
    soft_time_limit=1500,
)
def run_pipeline(self, job_id: str, topic_id: str, topic_name: str, max_papers: int = 8) -> dict:
    try:
        orchestrator = Orchestrator(job_id=job_id)
        return orchestrator.run(topic_id=topic_id, topic_name=topic_name, max_papers=max_papers)
    except Exception as exc:
        if not _retryable_pipeline_error(exc):
            raise
        # After in-loop LLM retries, give the queue another shot with backoff (rate limits / outages)
        countdown = min(90 * (2 ** self.request.retries), 600)
        raise self.retry(exc=exc, countdown=countdown)
