import os
import uuid

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-only-secret-with-at-least-32-characters"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def clients(tmp_path):
    test_url = os.getenv("TEST_DATABASE_URL", "sqlite://")
    postgres = test_url.startswith("postgresql")
    schema = f"test_{uuid.uuid4().hex}"
    if postgres:
        engine = create_engine(test_url)
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
        # LangGraph writes checkpoints from background threads. Each session
        # must own a connection rather than sharing an in-memory StaticPool.
        if test_url == "sqlite://":
            test_url = f"sqlite:///{tmp_path / 'marketmind.db'}"
        engine = create_engine(test_url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app.state.test_session_factory = factory
    app.state.disable_workflow_worker = True

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as first, TestClient(app) as second:
        yield first, second
    app.dependency_overrides.clear()
    del app.state.test_session_factory
    del app.state.disable_workflow_worker
    Base.metadata.drop_all(engine)
    if postgres:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}"'))
    engine.dispose()


def register(client, email="owner@example.com", industry="ecommerce"):
    response = client.post("/api/auth/register", json={"email": email, "password": "a-good-test-password",
                           "business_name": "Test Business", "industry": industry})
    assert response.status_code == 201, response.text
    return response.json()["workspace_id"]
