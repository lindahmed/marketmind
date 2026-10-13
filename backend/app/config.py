from functools import lru_cache
import os
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore", hide_input_in_errors=True)

    environment: Literal["development", "test", "production"] = "development"
    service_role: Literal["api", "worker"] = "api"
    database_url: str = Field(default="postgresql+psycopg://marketmind:marketmind@localhost:5432/marketmind", repr=False)
    jwt_secret: str = Field(min_length=32, repr=False)
    session_hours: int = Field(default=12, ge=1, le=168)
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:3000"]
    workflow_worker_enabled: bool = True
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=2, ge=0, le=10)
    worker_poll_seconds: float = Field(default=2, ge=0.1, le=30)
    worker_lease_seconds: int = Field(default=300, ge=30, le=1800)
    worker_heartbeat_seconds: float = Field(default=30, ge=1, le=60)
    n8n_webhook_url: str | None = None
    n8n_webhook_token: SecretStr | None = None
    n8n_callback_token: SecretStr | None = None
    embedding_provider: Literal["disabled", "openai"] = "disabled"
    openai_api_key: SecretStr | None = None
    embedding_model: Literal["text-embedding-3-small", "text-embedding-3-large"] = "text-embedding-3-small"
    embedding_timeout_seconds: float = Field(default=30, ge=1, le=60)
    investigation_provider: Literal["disabled", "openai"] = "disabled"
    strategy_provider: Literal["disabled", "openai"] = "disabled"
    investigation_model: Literal["gpt-4o-mini", "gpt-4o"] = "gpt-4o-mini"
    investigation_timeout_seconds: float = Field(default=45, ge=1, le=60)

    @model_validator(mode="after")
    def validate_provider_configuration(self):
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds / 2:
            raise ValueError("Worker heartbeat must be shorter than half the lease")
        if self.environment == "production":
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires PostgreSQL with the psycopg driver")
            if not self.cookie_secure or self.workflow_worker_enabled:
                raise ValueError("Production requires COOKIE_SECURE=true and WORKFLOW_WORKER_ENABLED=false")
            if not self.allowed_origins:
                raise ValueError("Production requires the exact public frontend origin")
            for origin in self.allowed_origins:
                parsed = urlsplit(origin)
                if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                        or parsed.path or parsed.query or parsed.fragment or "*" in origin
                        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
                    raise ValueError("Production ALLOWED_ORIGINS must contain exact HTTPS origins without a path")
            if self.n8n_webhook_url:
                parsed = urlsplit(self.n8n_webhook_url)
                if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".n8n.cloud")
                        or not parsed.path.startswith("/webhook/") or parsed.query or parsed.fragment
                        or parsed.username or parsed.password or parsed.port not in (None, 443)):
                    raise ValueError("Production requires an active HTTPS n8n Cloud /webhook/ URL")
                if not self.n8n_callback_token:
                    raise ValueError("Production n8n dispatch requires separate callback authentication")
        if "openai" in (self.embedding_provider, self.investigation_provider, self.strategy_provider) and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when an OpenAI provider is enabled")
        if bool(self.n8n_webhook_url) != bool(self.n8n_webhook_token and self.n8n_webhook_token.get_secret_value().strip()):
            raise ValueError("Configure both N8N_WEBHOOK_URL and N8N_WEBHOOK_TOKEN")
        if self.n8n_callback_token:
            callback_secret = self.n8n_callback_token.get_secret_value().strip()
            if len(callback_secret) < 32:
                raise ValueError("N8N_CALLBACK_TOKEN must contain at least 32 characters")
            if self.n8n_webhook_token and callback_secret == self.n8n_webhook_token.get_secret_value():
                raise ValueError("N8N_CALLBACK_TOKEN must be different from N8N_WEBHOOK_TOKEN")
        return self

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("jwt_secret")
    @classmethod
    def reject_example_secret(cls, value: str) -> str:
        if value.startswith("REPLACE_"):
            raise ValueError("Generate JWT_SECRET before starting the backend")
        return value


@lru_cache
def get_settings() -> Settings:
    # Railway injects variables; never load a developer's .env in production.
    return Settings(_env_file=None) if os.getenv("ENVIRONMENT") == "production" else Settings()
