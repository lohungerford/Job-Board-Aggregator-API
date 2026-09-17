from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Job Board Aggregator API"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/jobboard"
    redis_url: str = ""

    jwt_secret: str = "change-me-to-a-long-random-secret-at-least-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 7

    internal_ingest_secret: str = "change-me-internal-ingest-secret"

    cors_allow_origins: str = "*"

    rate_limit_anonymous: int = 30
    rate_limit_authenticated: int = 120
    rate_limit_api_key: int = 300
    rate_limit_window_seconds: int = 60

    greenhouse_timeout_seconds: float = 30.0
    ingest_concurrency: int = 4

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://") and "+asyncpg" not in value:
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_allow_origins.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    def require_production_secrets(self) -> None:
        """Refuse to boot in production with placeholder credentials."""
        if not self.is_production:
            return
        problems: list[str] = []
        if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("change-me"):
            problems.append("JWT_SECRET must be a unique value of at least 32 characters")
        if len(self.internal_ingest_secret) < 16 or self.internal_ingest_secret.startswith("change-me"):
            problems.append("INTERNAL_INGEST_SECRET must be a unique value of at least 16 characters")
        if problems:
            raise RuntimeError("; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
