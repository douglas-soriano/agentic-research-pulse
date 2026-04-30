from typing import Literal
from pydantic import BaseModel, field_validator


class QueryPlan(BaseModel):
    queries: list[str]

    @field_validator("queries")
    @classmethod
    def clean_and_cap(cls, v: list) -> list[str]:
        cleaned = [q.strip() for q in v if isinstance(q, str) and q.strip()]
        if not cleaned:
            raise ValueError("queries must contain at least one non-empty string")
        for q in cleaned:
            if "arxiv:" in q.lower():
                raise ValueError(
                    f"Query contains a fake arXiv ID: {q!r}. "
                    "Use only descriptive keywords, never arXiv IDs."
                )
            if q.startswith("[") and "]" in q:
                raise ValueError(
                    f"Query starts with a category tag like [physics.comp-ph]: {q!r}. "
                    "Use only descriptive keywords."
                )
        return cleaned[:3]


class ClaimItem(BaseModel):
    index: int
    text: str
    category: Literal["finding", "method", "limitation", "contribution"]
    confidence: float = 0.8


class ClaimsOutput(BaseModel):
    claims: list[ClaimItem]


class SynthesisOutput(BaseModel):
    synthesis: str

    @field_validator("synthesis")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("synthesis text cannot be empty")
        return v
