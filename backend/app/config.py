"""Central configuration. Every value can be overridden with an environment variable."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "AgentFlow"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg2://agentflow:agentflow@localhost:5432/agentflow"
    redis_url: str = "redis://localhost:6379/0"
    # Dev-only: run workflows in a background thread instead of Celery (no Redis needed).
    celery_eager: bool = False

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Any OpenAI-compatible provider. Default: Groq (free tier).
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_fallback_model: str = "llama-3.1-8b-instant"
    llm_timeout: float = 90.0
    llm_max_retries: int = 3

    # Local, free embeddings (no API key). "fastembed" (ONNX) or "hashing" (lightweight lexical).
    embedding_backend: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    upload_dir: str = "/data/uploads"
    report_dir: str = "/data/reports"
    max_upload_mb: int = 25

    # Optional SMTP (used only by the approval-gated send_email tool)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Render/Heroku/Neon give postgres:// or postgresql:// - SQLAlchemy needs the psycopg2 driver prefix.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg2://" + v[len(prefix):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "production" and s.jwt_secret == "change-me-in-production":
        raise RuntimeError("JWT_SECRET must be set when ENVIRONMENT=production")
    return s
