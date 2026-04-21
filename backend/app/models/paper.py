from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class Paper(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published_at: datetime
    topic_id: str
    full_text: str | None = None
    chunk_count: int = 0
    embedded: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PaperCreate(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published_at: datetime
    topic_id: str
