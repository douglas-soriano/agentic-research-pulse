from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str
    redis_url: str = "redis://localhost:6379/0"
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    database_url: str = "sqlite:////data/researchpulse.db"

    # Agent config
    llm_model: str = "gemini-2.0-flash"
    max_papers_per_topic: int = 8
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    max_tool_retries: int = 3
    # Gemini API rate limits / transient errors (429 RESOURCE_EXHAUSTED, etc.)
    # Free-tier limit: 15 req/min. Base ≥30 s ensures we stay well inside quota.
    llm_api_max_retries: int = 6
    llm_api_retry_base_seconds: float = 30.0
    llm_api_retry_max_seconds: float = 180.0

    @field_validator("gemini_api_key")
    @classmethod
    def _gemini_present(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError(
                "GEMINI_API_KEY is missing or empty. Set it in the project .env file "
                "(see .env.example) and rebuild containers so Celery/FastAPI can start."
            )
        return v


settings = Settings()
