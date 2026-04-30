import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.dlq_service import dlq_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/dlq", tags=["dlq"])


class DlqEntry(BaseModel):
    job_id: str
    error_message: str
    failed_at: str
    attempt_count: int
    original_payload: dict


class DlqListResponse(BaseModel):
    total: int
    entries: list[DlqEntry]


class RetryResponse(BaseModel):
    new_job_id: str
    original_job_id: str
    status: str


@router.get("", response_model=DlqListResponse)
def list_failed_jobs(limit: int = 50):
    entries = dlq_service.list_entries(limit=limit)
    total = dlq_service.count()
    return DlqListResponse(total=total, entries=[DlqEntry(**e) for e in entries])


@router.get("/{job_id}", response_model=DlqEntry)
def get_failed_job(job_id: str):
    entry = dlq_service.get_entry(job_id)
    if not entry:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return DlqEntry(**entry)


@router.post("/{job_id}/retry", response_model=RetryResponse)
def retry_failed_job(job_id: str):
    entry = dlq_service.get_entry(job_id)
    if not entry:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    payload = entry.get("original_payload", {})
    topic_id = payload.get("topic_id")
    topic_name = payload.get("topic_name")
    max_papers = payload.get("max_papers", 8)

    if not topic_id or not topic_name:
        raise HTTPException(
            status_code=422,
            detail="Cannot replay: missing topic_id or topic_name in original payload",
        )

    new_job_id = str(uuid.uuid4())

    from app.jobs.run_pipeline_job import run_pipeline
    from app.services.stream_service import stream_service

    stream_service.task_queued(new_job_id, topic_name)
    run_pipeline.delay(
        job_id=new_job_id,
        topic_id=topic_id,
        topic_name=topic_name,
        max_papers=max_papers,
    )


    dlq_service.remove(job_id)

    logger.info(
        "dlq_job_replayed",
        original_job_id=job_id,
        new_job_id=new_job_id,
        topic=topic_name,
    )
    return RetryResponse(
        new_job_id=new_job_id,
        original_job_id=job_id,
        status="requeued",
    )
