"""
process_paper_job — fetch, chunk, and embed a single paper.
Called per-paper during the pipeline; can be enqueued individually for reruns.
"""
from celery_worker import celery_app
from app.services.paper_service import PaperService


@celery_app.task(
    name="jobs.process_paper",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def process_paper(self, paper_meta: dict, topic_id: str) -> dict:
    try:
        service = PaperService()
        paper = service.ingest(paper_meta, topic_id)
        return {
            "paper_id": paper.id,
            "arxiv_id": paper.arxiv_id,
            "embedded": paper.embedded,
            "chunk_count": paper.chunk_count,
        }
    except Exception as exc:
        raise self.retry(exc=exc)
