import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import ReviewRow
from app.models.review import Review, ReviewCreate, CitedPaper


class ReviewRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: ReviewCreate) -> Review:
        row = ReviewRow(
            id=str(uuid.uuid4()),
            topic_id=data.topic_id,
            topic_name=data.topic_name,
            synthesis=data.synthesis,
            citations=json.dumps(data.citations),
            cited_papers=json.dumps([p.model_dump() for p in data.cited_papers]),
            papers_processed=data.papers_processed,
            claims_extracted=data.claims_extracted,
            citations_verified=data.citations_verified,
            citations_rejected=data.citations_rejected,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._to_model(row)

    def get_latest_by_topic(self, topic_id: str) -> Review | None:
        row = (
            self.session.query(ReviewRow)
            .filter_by(topic_id=topic_id)
            .order_by(ReviewRow.version.desc())
            .first()
        )
        return self._to_model(row) if row else None

    def get_all_by_topic(self, topic_id: str) -> list[Review]:
        rows = (
            self.session.query(ReviewRow)
            .filter_by(topic_id=topic_id)
            .order_by(ReviewRow.version.desc())
            .all()
        )
        return [self._to_model(r) for r in rows]

    def update(
        self,
        review_id: str,
        synthesis: str,
        citations: dict,
        cited_papers: list[CitedPaper],
        stats: dict,
    ) -> None:
        row = self.session.query(ReviewRow).filter_by(id=review_id).first()
        if not row:
            return
        row.synthesis = synthesis
        row.citations = json.dumps(citations)
        row.cited_papers = json.dumps([p.model_dump() for p in cited_papers])
        row.version += 1
        row.updated_at = datetime.utcnow()
        row.papers_processed = stats.get("papers_processed", row.papers_processed)
        row.claims_extracted = stats.get("claims_extracted", row.claims_extracted)
        row.citations_verified = stats.get("citations_verified", row.citations_verified)
        row.citations_rejected = stats.get("citations_rejected", row.citations_rejected)
        self.session.commit()

    def _to_model(self, row: ReviewRow) -> Review:
        cited_papers = [CitedPaper(**p) for p in json.loads(row.cited_papers)]
        citations_raw = row.citations if row.citations else "{}"
        return Review(
            id=row.id,
            topic_id=row.topic_id,
            topic_name=row.topic_name,
            synthesis=row.synthesis,
            citations=json.loads(citations_raw),
            cited_papers=cited_papers,
            papers_processed=row.papers_processed,
            claims_extracted=row.claims_extracted,
            citations_verified=row.citations_verified,
            citations_rejected=row.citations_rejected,
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
