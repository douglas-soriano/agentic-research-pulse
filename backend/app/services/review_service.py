from app.database import get_session
from app.models.review import Review, ReviewCreate, CitedPaper
from app.repositories.review_repository import ReviewRepository


class ReviewService:
    def save(self, data: ReviewCreate) -> Review:
        with get_session() as session:
            repo = ReviewRepository(session)
            existing = repo.get_latest_by_topic(data.topic_id)
            if existing:
                repo.update(
                    review_id=existing.id,
                    synthesis=data.synthesis,
                    citations=data.citations,
                    cited_papers=data.cited_papers,
                    stats={
                        "papers_processed": data.papers_processed,
                        "claims_extracted": data.claims_extracted,
                        "citations_verified": data.citations_verified,
                        "citations_rejected": data.citations_rejected,
                    },
                )
                return repo.get_latest_by_topic(data.topic_id)
            return repo.create(data)

    def get_by_id(self, review_id: str) -> Review | None:
        with get_session() as session:
            repo = ReviewRepository(session)
            return repo.get_by_id(review_id)

    def get_latest(self, topic_id: str) -> Review | None:
        with get_session() as session:
            repo = ReviewRepository(session)
            return repo.get_latest_by_topic(topic_id)

    def get_history(self, topic_id: str) -> list[Review]:
        with get_session() as session:
            repo = ReviewRepository(session)
            return repo.get_all_by_topic(topic_id)
