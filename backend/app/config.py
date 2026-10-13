from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://marketmind:marketmind@localhost:5432/marketmind"
    jwt_secret: str = Field(min_length=32)
    session_hours: int = Field(default=12, ge=1, le=168)
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:3000"]
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

    @field_validator("jwt_secret")
    @classmethod
    def reject_example_secret(cls, value: str) -> str:
        if value.startswith("REPLACE_"):
            raise ValueError("Generate JWT_SECRET before starting the backend")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
