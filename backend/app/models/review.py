from datetime import datetime
from pydantic import BaseModel, Field
import uuid

from app.utils.time import utc_now


class CitedPaper(BaseModel):
    paper_id: str
    arxiv_id: str
    title: str
    authors: list[str]
    chunk_ids: list[str]


class CitationEntry(BaseModel):
    paper_id: str
    arxiv_id: str
    title: str
    authors: list[str]
    chunk_id: str


class Review(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic_id: str
    topic_name: str
    synthesis: str
    citations: dict[str, dict] = Field(default_factory=dict)
    cited_papers: list[CitedPaper]
    papers_processed: int
    claims_extracted: int
    citations_verified: int
    citations_rejected: int
    version: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReviewCreate(BaseModel):
    topic_id: str
    topic_name: str
    synthesis: str
    citations: dict[str, dict] = Field(default_factory=dict)
    cited_papers: list[CitedPaper]
    papers_processed: int
    claims_extracted: int
    citations_verified: int
    citations_rejected: int
