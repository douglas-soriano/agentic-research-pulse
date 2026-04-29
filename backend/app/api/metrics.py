from fastapi import APIRouter
from pydantic import BaseModel

from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["metrics"])
metrics_service = MetricsService()


class MetricsResponse(BaseModel):
    total_jobs_processed: int
    average_duration_ms: float
    citation_correctness_rate: float
    error_rate: float


@router.get("", response_model=MetricsResponse)
def get_metrics():
    metrics = metrics_service.get_metrics()
    return MetricsResponse(
        total_jobs_processed=metrics.total_jobs_processed,
        average_duration_ms=metrics.average_duration_ms,
        citation_correctness_rate=metrics.citation_correctness_rate,
        error_rate=metrics.error_rate,
    )
