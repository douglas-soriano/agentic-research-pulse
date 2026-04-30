import uuid
from datetime import datetime, timedelta

import structlog

from celery_worker import celery_app
from app.tools.arxiv_tools import search_arxiv
from app.services.topic_service import TopicService
from app.utils.time import utc_now

logger = structlog.get_logger(__name__)


@celery_app.task(name="jobs.refresh_reviews", acks_late=True)
def refresh_reviews() -> dict:
    from app.jobs.run_pipeline_job import run_pipeline

    refreshed = []
    topic_service = TopicService()
    topics = topic_service.list_all()

    for topic in topics:
        cutoff = topic.last_fetched_at or (utc_now() - timedelta(days=7))
        try:
            result = search_arxiv(topic.name, max_results=3)
            new_papers = [
                p for p in result["papers"]
                if datetime.fromisoformat(p["published_at"].replace("Z", "+00:00")).replace(tzinfo=None) > cutoff
            ]
            if new_papers:
                job_id = str(uuid.uuid4())
                run_pipeline.delay(
                    job_id=job_id,
                    topic_id=topic.id,
                    topic_name=topic.name,
                    max_papers=5,
                )
                refreshed.append({"topic": topic.name, "new_papers": len(new_papers)})
                topic_service.mark_fetched(topic.id)
        except Exception as exc:
            logger.warning("refresh_review_topic_failed", topic_id=topic.id, topic=topic.name, error=str(exc))
            refreshed.append({"topic": topic.name, "error": str(exc)})

    return {"refreshed": refreshed, "count": len(refreshed)}
