from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str
    redis_url: str = "redis://localhost:6379/0"
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    database_url: str = "sqlite:////data/researchpulse.db"

    # Agent config
    llm_model: str = "llama-3.3-70b-versatile"
    max_papers_per_topic: int = 5
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    max_tool_retries: int = 3
    # Groq free tier: ~30 RPM for Llama 70B. Retry-After header guides actual delay.
    llm_api_max_retries: int = 6
    llm_api_retry_base_seconds: float = 10.0
    llm_api_retry_max_seconds: float = 120.0

    # Hard cap on total LLM API calls per pipeline job.
    # Shared across all agents (Search + Extract × N papers + Synthesis).
    max_llm_calls_per_job: int = 60

    @field_validator("groq_api_key")
    @classmethod
    def _groq_present(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError(
                "GROQ_API_KEY is missing or empty. Set it in the project .env file "
                "and rebuild containers so Celery/FastAPI can start."
            )
        return v


settings = Settings()
