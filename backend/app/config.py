from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM provider — defaults to local Ollama. Override via env vars for Groq:
    #   LLM_BASE_URL=https://api.groq.com/openai/v1
    #   LLM_API_KEY=gsk_...
    #   LLM_MODEL=llama-3.3-70b-versatile
    llm_base_url: str = "http://host.docker.internal:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b"

    redis_url: str = "redis://localhost:6379/0"
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    database_url: str = "sqlite:////data/researchpulse.db"

    # Agent config
    max_papers_per_topic: int = 5
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    max_tool_retries: int = 3
    llm_api_max_retries: int = 4
    llm_api_retry_base_seconds: float = 5.0
    llm_api_retry_max_seconds: float = 60.0
    max_llm_calls_per_job: int = 60


settings = Settings()
