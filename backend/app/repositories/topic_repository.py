import uuid

from sqlalchemy.orm import Session

from app.database import TopicRow
from app.models.topic import Topic
from app.utils.time import utc_now


class TopicRepository:
    def __init__(self, session: Session):
        self.session = session

    def find(self, topic_id: str) -> Topic | None:
        row = self.session.query(TopicRow).filter_by(id=topic_id).first()
        return self._to_model(row) if row else None

    def find_by(self, criteria: dict, relationships: list[str] | None = None) -> list[Topic]:
        query = self.session.query(TopicRow)
        for column_name, value in criteria.items():
            query = query.filter(getattr(TopicRow, column_name) == value)
        rows = query.order_by(TopicRow.created_at.desc()).all()
        return [self._to_model(row) for row in rows]

    def save(self, topic: Topic) -> Topic:
        row = TopicRow(
            id=topic.id,
            name=topic.name,
            last_fetched_at=topic.last_fetched_at,
            created_at=topic.created_at,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._to_model(row)

    def get_or_create(self, name: str) -> Topic:
        row = self.session.query(TopicRow).filter_by(name=name).first()
        if row:
            return self._to_model(row)
        return self.save(Topic(id=str(uuid.uuid4()), name=name, created_at=utc_now()))

    def list_all(self) -> list[Topic]:
        rows = self.session.query(TopicRow).order_by(TopicRow.created_at.desc()).all()
        return [self._to_model(row) for row in rows]

    def mark_fetched(self, topic_id: str) -> None:
        self.session.query(TopicRow).filter_by(id=topic_id).update(
            {"last_fetched_at": utc_now()}
        )
        self.session.commit()

    def _to_model(self, row: TopicRow) -> Topic:
        return Topic(
            id=row.id,
            name=row.name,
            last_fetched_at=row.last_fetched_at,
            created_at=row.created_at,
        )
