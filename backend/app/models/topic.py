from datetime import datetime

from pydantic import BaseModel


class Topic(BaseModel):
    id: str
    name: str
    last_fetched_at: datetime | None = None
    created_at: datetime
