from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.review_service import ReviewService

router = APIRouter(prefix="/reviews", tags=["reviews"])
review_service = ReviewService()


class CitedPaperResponse(BaseModel):
    paper_id: str
    arxiv_id: str
    title: str
    authors: list[str]
    chunk_ids: list[str]


class CitationEntryResponse(BaseModel):
    """Single entry in the citations map: keyed by the 4-digit token XXXX."""
    paper_id: str
    arxiv_id: str
    title: str
    authors: list[str]
    chunk_id: str


class ReviewResponse(BaseModel):
    id: str
    topic_id: str
    topic_name: str
    # Synthesis text with inline [citation_XXXX] tokens.
    # Never rewrite this field — render it by substituting tokens from the map below.
    synthesis: str
    # Map from token key ("0001") → citation metadata.
    # Frontend resolves [citation_0001] → citations["0001"]
    citations: dict[str, CitationEntryResponse]
    cited_papers: list[CitedPaperResponse]
    papers_processed: int
    claims_extracted: int
    citations_verified: int
    citations_rejected: int
    version: int
    created_at: datetime
    updated_at: datetime


def _build_citation_entry(raw: dict) -> CitationEntryResponse:
    return CitationEntryResponse(
        paper_id=raw.get("paper_id", ""),
        arxiv_id=raw.get("arxiv_id", ""),
        title=raw.get("title", ""),
        authors=raw.get("authors", []),
        chunk_id=raw.get("chunk_id", ""),
    )


def _to_response(review) -> ReviewResponse:
    citations = {
        key: _build_citation_entry(val)
        for key, val in review.citations.items()
    }
    return ReviewResponse(
        id=review.id,
        topic_id=review.topic_id,
        topic_name=review.topic_name,
        synthesis=review.synthesis,
        citations=citations,
        cited_papers=[
            CitedPaperResponse(**p.model_dump()) for p in review.cited_papers
        ],
        papers_processed=review.papers_processed,
        claims_extracted=review.claims_extracted,
        citations_verified=review.citations_verified,
        citations_rejected=review.citations_rejected,
        version=review.version,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.get("/{topic_id}", response_model=ReviewResponse)
def get_review(topic_id: str):
    review = review_service.get_latest(topic_id)
    if not review:
        raise HTTPException(status_code=404, detail="No review found for this topic yet")
    return _to_response(review)


@router.get("/{topic_id}/history", response_model=list[ReviewResponse])
def get_review_history(topic_id: str):
    reviews = review_service.get_history(topic_id)
    return [_to_response(r) for r in reviews]
