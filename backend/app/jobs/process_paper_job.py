import structlog
from celery_worker import celery_app
from app.services.paper_service import PaperService
from app.tools.vector_tools import paper_has_chunks

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="jobs.process_paper",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def process_paper(self, paper_meta: dict, topic_id: str) -> dict:
    arxiv_id = paper_meta.get("arxiv_id", "")

    try:
        if arxiv_id and paper_has_chunks(arxiv_id):
            logger.info(
                "paper_skipped_already_embedded",
                arxiv_id=arxiv_id,
                step="idempotency_check",
            )
            return {
                "arxiv_id": arxiv_id,
                "skipped": True,
                "reason": "already_in_chromadb",
            }

        service = PaperService()
        paper = service.ingest(paper_meta, topic_id)
        return {
            "paper_id": paper.id,
            "arxiv_id": paper.arxiv_id,
            "embedded": paper.embedded,
            "chunk_count": paper.chunk_count,
        }
    except Exception as exc:
        logger.warning(
            "process_paper_failed",
            arxiv_id=arxiv_id,
            attempt=self.request.retries,
            error=str(exc),
        )
        raise self.retry(exc=exc)
