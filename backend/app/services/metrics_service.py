from app.database import get_session
from app.models.metrics import Metrics
from app.repositories.trace_repository import TraceRepository


class MetricsService:
    def get_metrics(self) -> Metrics:
        with get_session() as session:
            repository = TraceRepository(session)
            return repository.metrics()
