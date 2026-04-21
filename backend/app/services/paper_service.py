"""
PaperService — orchestrates single-paper ingestion:
fetch full text → store in DB → chunk + embed → mark embedded.
"""
from datetime import datetime

from app.database import get_session
from app.models.paper import Paper, PaperCreate
from app.repositories.paper_repository import PaperRepository
from app.services.embedding_service import EmbeddingService
from app.tools.arxiv_tools import fetch_paper


class PaperService:
    def __init__(self):
        self.embedding_service = EmbeddingService()

    def ingest(self, paper_meta: dict, topic_id: str) -> Paper:
        """
        Full ingestion pipeline for one paper:
        1. Persist metadata (idempotent — skip if already exists)
        2. Fetch full text
        3. Chunk + embed into ChromaDB
        4. Mark embedded in DB
        """
        with get_session() as session:
            repo = PaperRepository(session)
            existing = repo.get_by_arxiv_id(paper_meta["arxiv_id"])
            if existing and existing.embedded:
                return existing  # Already fully processed

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

        # Fetch full text outside the session (network call)
        result = fetch_paper(paper.arxiv_id)
        full_text = result.get("text", paper.abstract)
        if not full_text:
            full_text = paper.abstract

        with get_session() as session:
            repo = PaperRepository(session)
            repo.update_full_text(paper.id, full_text)

        # Chunk + embed
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
            return refreshed or paper

    def get_papers_for_topic(self, topic_id: str) -> list[Paper]:
        with get_session() as session:
            repo = PaperRepository(session)
            return repo.get_by_topic(topic_id)
