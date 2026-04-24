from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.pipelines.research_pipeline import ResearchPipeline

router = APIRouter(prefix="/topics", tags=["topics"])
pipeline = ResearchPipeline()


class TopicRequest(BaseModel):
    name: str
    max_papers: int = 8


class TopicResponse(BaseModel):
    id: str
    name: str
    job_id: str | None = None
    created_at: datetime


class TopicListItem(BaseModel):
    id: str
    name: str
    last_fetched_at: datetime | None
    latest_job_id: str | None = None
    created_at: datetime


@router.post("", response_model=TopicResponse, status_code=202)
def create_topic(req: TopicRequest):
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="Topic name cannot be empty")

    topic = pipeline.get_or_create_topic(req.name.strip())
    job_id = pipeline.start(topic.id, topic.name, req.max_papers)
    return TopicResponse(id=topic.id, name=topic.name, job_id=job_id, created_at=topic.created_at)


@router.get("", response_model=list[TopicListItem])
def list_topics():
    topics = pipeline.list_topics()
    job_ids = pipeline.latest_job_ids([t.name for t in topics])
    return [
        TopicListItem(
            id=t.id,
            name=t.name,
            last_fetched_at=t.last_fetched_at,
            latest_job_id=job_ids.get(t.name),
            created_at=t.created_at,
        )
        for t in topics
    ]
