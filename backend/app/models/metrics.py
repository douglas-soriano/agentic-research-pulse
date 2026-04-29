from pydantic import BaseModel


class Metrics(BaseModel):
    total_jobs_processed: int
    average_duration_ms: float
    citation_correctness_rate: float
    error_rate: float
