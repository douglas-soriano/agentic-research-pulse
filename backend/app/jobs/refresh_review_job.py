"""
refresh_review_job — periodic job (Celery Beat, hourly) that checks arXiv for
papers newer than the last pipeline run and re-runs the pipeline if new papers exist.
"""
import uuid
from datetime import datetime, timedelta

from celery_worker import celery_app
from app.database import get_session, TopicRow
from app.tools.arxiv_tools import search_arxiv
from app.repositories.paper_repository import PaperRepository


@celery_app.task(name="jobs.refresh_reviews", acks_late=True)
def refresh_reviews() -> dict:
    """Enqueues run_pipeline for any topic that has new arXiv papers."""
    from app.jobs.run_pipeline_job import run_pipeline

    refreshed = []
    with get_session() as session:
        topics = session.query(TopicRow).all()

    for topic in topics:
        cutoff = topic.last_fetched_at or (datetime.utcnow() - timedelta(days=7))
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
                # Update last_fetched_at
                with get_session() as session:
                    session.query(TopicRow).filter_by(id=topic.id).update(
                        {"last_fetched_at": datetime.utcnow()}
                    )
                    session.commit()
        except Exception as exc:
            refreshed.append({"topic": topic.name, "error": str(exc)})

    return {"refreshed": refreshed, "count": len(refreshed)}
