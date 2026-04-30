from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.database import init_db
from app.observability.logging import configure_logging

configure_logging()

celery_app = Celery(
    "researchpulse",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.jobs.process_paper_job",
        "app.jobs.run_pipeline_job",
        "app.jobs.refresh_review_job",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "refresh-reviews-hourly": {
            "task": "jobs.refresh_reviews",
            "schedule": crontab(minute=0),
        },
    },
)


@celery_app.on_after_finalize.connect
def setup_db(sender, **kwargs):
    init_db()
