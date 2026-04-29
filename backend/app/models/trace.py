from datetime import datetime
from pydantic import BaseModel, Field
import uuid

from app.utils.time import utc_now


class TraceStep(BaseModel):
    agent: str
    tool: str | None = None
    input: dict
    output: dict
    duration_ms: int
    success: bool
    error: str | None = None
    token_count: int | None = None
    cost_usd: float | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class Trace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    topic: str
    status: str = "running"
    steps: list[TraceStep] = Field(default_factory=list)
    total_duration_ms: int = 0
    papers_processed: int = 0
    claims_extracted: int = 0
    citations_verified: int = 0
    citations_rejected: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class TraceCreate(BaseModel):
    job_id: str
    topic: str
