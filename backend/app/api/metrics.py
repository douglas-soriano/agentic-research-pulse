"""
Metrics endpoint — aggregated pipeline statistics from the trace store.
GET /api/v1/metrics
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.database import get_session, TraceRow
from sqlalchemy import func

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricsResponse(BaseModel):
    total_jobs_processed: int
    average_duration_ms: float
    citation_correctness_rate: float
    error_rate: float


@router.get("", response_model=MetricsResponse)
def get_metrics():
    with get_session() as session:
        total = session.query(func.count(TraceRow.id)).scalar() or 0
        failed = (
            session.query(func.count(TraceRow.id))
            .filter(TraceRow.status == "failed")
            .scalar() or 0
        )

        last_100_durations = (
            session.query(TraceRow.total_duration_ms)
            .filter(TraceRow.status == "completed")
            .order_by(TraceRow.created_at.desc())
            .limit(100)
            .all()
        )
        durations = [r[0] for r in last_100_durations if r[0] is not None]
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        citation_row = session.query(
            func.sum(TraceRow.citations_verified),
            func.sum(TraceRow.citations_rejected),
        ).filter(TraceRow.status == "completed").first()

        verified = int(citation_row[0] or 0)
        rejected = int(citation_row[1] or 0)
        total_claims = verified + rejected
        correctness_rate = verified / total_claims if total_claims > 0 else 0.0

        error_rate = failed / total if total > 0 else 0.0

    return MetricsResponse(
        total_jobs_processed=total,
        average_duration_ms=round(avg_duration, 2),
        citation_correctness_rate=round(correctness_rate, 4),
        error_rate=round(error_rate, 4),
    )
