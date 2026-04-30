from datetime import datetime

import structlog

from app.database import get_session
from app.exceptions import ExternalServiceError
from app.models.paper import Paper, PaperCreate
from app.repositories.paper_repository import PaperRepository
from app.services.embedding_service import EmbeddingService
from app.tools.arxiv_tools import fetch_paper

logger = structlog.get_logger(__name__)


class PaperService:
    def __init__(self):
        self.embedding_service = EmbeddingService()

    def ingest(self, paper_meta: dict, topic_id: str) -> Paper:
        with get_session() as session:
            repo = PaperRepository(session)
            existing = repo.get_by_arxiv_id(paper_meta["arxiv_id"])
            if existing and existing.embedded:
                logger.info("paper_already_embedded", arxiv_id=paper_meta["arxiv_id"])
                return existing

            if not existing:
                paper = repo.create(
                    PaperCreate(
                        arxiv_id=paper_meta["arxiv_id"],
                        title=paper_meta["title"],
                        authors=paper_meta["authors"],
                        abstract=paper_meta["abstract"],
                        published_at=datetime.fromisoformat(paper_meta["published_at"]),
                        topic_id=topic_id,
                    )
                )
            else:
                paper = existing


        if paper.arxiv_id.startswith("10."):
            full_text = paper.abstract or ""
        else:
            try:
                fetched_paper = fetch_paper(paper.arxiv_id)
                full_text = fetched_paper.get("text", paper.abstract)
            except ExternalServiceError as exc:
                logger.warning("paper_fetch_failed", arxiv_id=paper.arxiv_id, error=str(exc))
                full_text = paper.abstract
        if not full_text:
            full_text = paper.abstract

        with get_session() as session:
            repo = PaperRepository(session)
            repo.update_full_text(paper.id, full_text)


        chunk_count = self.embedding_service.chunk_and_embed(
            paper_id=paper.id,
            arxiv_id=paper.arxiv_id,
            title=paper.title,
            text=full_text,
        )

        with get_session() as session:
            repo = PaperRepository(session)
            repo.mark_embedded(paper.id, chunk_count)
            refreshed = repo.get_by_arxiv_id(paper.arxiv_id)
            logger.info("paper_ingested", arxiv_id=paper.arxiv_id, chunk_count=chunk_count)
            return refreshed or paper

    def get_papers_for_topic(self, topic_id: str) -> list[Paper]:
        with get_session() as session:
            repo = PaperRepository(session)
            return repo.get_by_topic(topic_id)
