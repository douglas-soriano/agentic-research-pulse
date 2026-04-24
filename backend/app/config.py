from dataclasses import dataclass

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"

_LOCAL_BASE_URL = "http://host.docker.internal:11434/v1"
_LOCAL_DEFAULT_MODEL = "qwen2.5:7b"


@dataclass
class ProviderConfig:
    base_url: str
    api_key: str
    model: str
    name: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Set LLM_PROVIDER=gemini (default) or LLM_PROVIDER=local in .env
    llm_provider: str = "gemini"
    gemini_api_key: str = ""

    # Resolved by the validator below — do not set these manually when using a provider
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

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

    def get_provider_chain(self) -> list[ProviderConfig]:
        """Returns [primary, fallback]. Primary = configured LLM_PROVIDER.
        Fallback = local Ollama, unless primary already is local."""
        primary = ProviderConfig(
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            model=self.llm_model,
            name=self.llm_provider,
        )
        if self.llm_provider == "local":
            return [primary]
        fallback = ProviderConfig(
            base_url=_LOCAL_BASE_URL,
            api_key="ollama",
            model=_LOCAL_DEFAULT_MODEL,
            name="local",
        )
        return [primary, fallback]

    @model_validator(mode="after")
    def resolve_llm_config(self) -> "Settings":
        if self.llm_provider == "local":
            if not self.llm_base_url:
                self.llm_base_url = _LOCAL_BASE_URL
            if not self.llm_api_key:
                self.llm_api_key = "ollama"
            if not self.llm_model:
                self.llm_model = _LOCAL_DEFAULT_MODEL
        else:
            self.llm_base_url = _GEMINI_BASE_URL
            self.llm_api_key = self.gemini_api_key
            if not self.llm_model:
                self.llm_model = _GEMINI_DEFAULT_MODEL
        return self


settings = Settings()
