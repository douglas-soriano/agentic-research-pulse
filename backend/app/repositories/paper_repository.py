import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import PaperRow
from app.models.paper import Paper, PaperCreate


class PaperRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: PaperCreate) -> Paper:
        row = PaperRow(
            id=str(uuid.uuid4()),
            arxiv_id=data.arxiv_id,
            title=data.title,
            authors=json.dumps(data.authors),
            abstract=data.abstract,
            published_at=data.published_at,
            topic_id=data.topic_id,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._to_model(row)

    def get_by_arxiv_id(self, arxiv_id: str) -> Paper | None:
        row = self.session.query(PaperRow).filter_by(arxiv_id=arxiv_id).first()
        return self._to_model(row) if row else None

    def get_by_topic(self, topic_id: str) -> list[Paper]:
        rows = self.session.query(PaperRow).filter_by(topic_id=topic_id).all()
        return [self._to_model(r) for r in rows]

    def mark_embedded(self, paper_id: str, chunk_count: int) -> None:
        self.session.query(PaperRow).filter_by(id=paper_id).update(
            {"embedded": True, "chunk_count": chunk_count}
        )
        self.session.commit()

    def update_full_text(self, paper_id: str, text: str) -> None:
        self.session.query(PaperRow).filter_by(id=paper_id).update({"full_text": text})
        self.session.commit()

    def _to_model(self, row: PaperRow) -> Paper:
        return Paper(
            id=row.id,
            arxiv_id=row.arxiv_id,
            title=row.title,
            authors=json.loads(row.authors),
            abstract=row.abstract,
            published_at=row.published_at,
            topic_id=row.topic_id,
            full_text=row.full_text,
            chunk_count=row.chunk_count,
            embedded=row.embedded,
            created_at=row.created_at,
        )
