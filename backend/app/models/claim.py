from pydantic import BaseModel, Field
import uuid


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    paper_id: str
    chunk_id: str
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    category: str
    verified: bool = False


class ClaimCreate(BaseModel):
    paper_id: str
    chunk_id: str
    text: str
    confidence: float
    category: str
