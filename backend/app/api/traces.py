from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.trace_service import TraceService

router = APIRouter(prefix="/traces", tags=["traces"])
trace_service = TraceService()


class TraceStepResponse(BaseModel):
    agent: str
    tool: str | None
    input: dict
    output: dict
    duration_ms: int
    success: bool
    error: str | None
    timestamp: datetime


class TraceResponse(BaseModel):
    id: str
    job_id: str
    topic: str
    status: str
    steps: list[TraceStepResponse]
    total_duration_ms: int
    papers_processed: int
    claims_extracted: int
    citations_verified: int
    citations_rejected: int
    created_at: datetime
    completed_at: datetime | None


@router.get("/{job_id}", response_model=TraceResponse)
def get_trace(job_id: str):
    trace = trace_service.get(job_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return TraceResponse(
        id=trace.id,
        job_id=trace.job_id,
        topic=trace.topic,
        status=trace.status,
        steps=[TraceStepResponse(**s.model_dump()) for s in trace.steps],
        total_duration_ms=trace.total_duration_ms,
        papers_processed=trace.papers_processed,
        claims_extracted=trace.claims_extracted,
        citations_verified=trace.citations_verified,
        citations_rejected=trace.citations_rejected,
        created_at=trace.created_at,
        completed_at=trace.completed_at,
    )


@router.get("", response_model=list[TraceResponse])
def list_traces(limit: int = 20):
    traces = trace_service.list_recent(limit=limit)
    return [
        TraceResponse(
            id=t.id,
            job_id=t.job_id,
            topic=t.topic,
            status=t.status,
            steps=[TraceStepResponse(**s.model_dump()) for s in t.steps],
            total_duration_ms=t.total_duration_ms,
            papers_processed=t.papers_processed,
            claims_extracted=t.claims_extracted,
            citations_verified=t.citations_verified,
            citations_rejected=t.citations_rejected,
            created_at=t.created_at,
            completed_at=t.completed_at,
        )
        for t in traces
    ]
