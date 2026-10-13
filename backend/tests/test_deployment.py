import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.auth import enforce_origin
from app.config import Settings


def production_settings(**overrides):
    values = dict(environment="production", database_url="postgres://marketmind_api:fake@db:5432/marketmind",
                  jwt_secret="fictional-test-secret-at-least-32-characters", cookie_secure=True,
                  workflow_worker_enabled=False, allowed_origins=["https://web.example"])
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.parametrize("overrides", [
    {"cookie_secure": False}, {"workflow_worker_enabled": True}, {"database_url": "sqlite:///preview.db"},
    {"allowed_origins": []}, {"allowed_origins": ["*"]}, {"allowed_origins": ["http://web.example"]},
    {"allowed_origins": ["https://web.example/path"]}, {"allowed_origins": ["https://user:pass@web.example"]},
    {"allowed_origins": ["https://localhost"]}, {"worker_heartbeat_seconds": 30, "worker_lease_seconds": 30},
    {"n8n_webhook_url": "https://fictional.app.n8n.cloud/webhook-test/simulation",
     "n8n_webhook_token": "fictional-token", "n8n_callback_token": "fictional-separate-callback-secret-000"},
])
def test_unsafe_production_configuration_fails_closed(overrides):
    with pytest.raises(ValidationError):
        production_settings(**overrides)


def test_railway_database_urls_normalize_without_losing_options():
    settings = production_settings(database_url="postgresql://marketmind_api:fake@db:5432/app?sslmode=require")
    assert settings.database_url == "postgresql+psycopg://marketmind_api:fake@db:5432/app?sslmode=require"
    assert "fictional-test-secret" not in repr(settings)
    assert "marketmind_api:fake" not in repr(settings)


def test_production_origin_checks_include_missing_origin_and_callback_exceptions(monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", production_settings)

    def request(path, origin=None):
        return Request({"type": "http", "method": "POST", "path": path,
                        "headers": [(b"origin", origin.encode())] if origin else []})

    for path in ("/api/auth/login", "/api/auth/register", "/api/workflow-jobs"):
        with pytest.raises(HTTPException) as error:
            enforce_origin(request(path))
        assert error.value.status_code == 403
        enforce_origin(request(path, "https://web.example"))
        with pytest.raises(HTTPException):
            enforce_origin(request(path, "https://hostile.example"))
    enforce_origin(request("/api/integrations/n8n/simulation-callback"))
    enforce_origin(request("/api/integrations/google-sheets/source-id/ingest"))
