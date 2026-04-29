from app.database import get_session
from app.models.topic import Topic
from app.repositories.topic_repository import TopicRepository


class TopicService:
    def get_or_create(self, name: str) -> Topic:
        with get_session() as session:
            repository = TopicRepository(session)
            return repository.get_or_create(name)

    def list_all(self) -> list[Topic]:
        with get_session() as session:
            repository = TopicRepository(session)
            return repository.list_all()

    def mark_fetched(self, topic_id: str) -> None:
        with get_session() as session:
            repository = TopicRepository(session)
            repository.mark_fetched(topic_id)
