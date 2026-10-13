"""Full release and restricted-role checks on an explicitly disposable cluster.

TEST_DEPLOYMENT_DATABASE_URL must have CREATEDB/CREATEROLE privileges. These
tests create/drop a database and the fixed runtime roles. Refuse existing roles
so an application cluster can never be changed by accident.
"""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.base import Base
from app.config import get_settings
from app.db import get_db, set_db_scope
from app.deployment import EXPECTED_REVISION, check_database
from app.job_lease import renew_lease
from app.models import DailyMetric, InvestigationRun, WorkflowJob
from app.workflow_jobs import _claim_job, _recover_expired, process_next_job
from tests.conftest import register
from tests.test_data_sources import batch, create_source, ecom_records
from tests.test_experiment_feedback import callback_body, post_callback
from tests.test_growth_strategy import approve, create_design, profile

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DEPLOYMENT_DATABASE_URL"),
                                reason="Disposable PostgreSQL cluster not configured")


@pytest.fixture(scope="module")
def release_database():
    admin = create_engine(os.environ["TEST_DEPLOYMENT_DATABASE_URL"], isolation_level="AUTOCOMMIT", hide_parameters=True)
    name = f"railway_release_{uuid.uuid4().hex}"
    passwords = {"marketmind_api": secrets.token_urlsafe(32), "marketmind_worker": secrets.token_urlsafe(32)}
    with admin.connect() as connection:
        assert not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles "
                                          "WHERE rolname IN ('marketmind_api', 'marketmind_worker'))")), (
            "Use a disposable cluster without existing MarketMind runtime roles")
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin_url = admin.url.set(database=name)
    root = Path(__file__).parents[1]
    engines = {"admin": create_engine(admin_url, hide_parameters=True)}
    try:
        env = os.environ | {"MIGRATION_DATABASE_URL": admin_url.render_as_string(hide_password=False),
                            "API_DATABASE_PASSWORD": passwords["marketmind_api"],
                            "WORKER_DATABASE_PASSWORD": passwords["marketmind_worker"], "ENVIRONMENT": "production"}
        migrated = subprocess.run([sys.executable, "-m", "app.migrate"], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=120)
        assert migrated.returncode == 0, migrated.stdout + migrated.stderr
        # Repeat the real command: idempotent migrations and role grants.
        repeated = subprocess.run([sys.executable, "-m", "app.migrate"], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=120)
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        for kind, role in (("api", "marketmind_api"), ("worker", "marketmind_worker")):
            engines[kind] = create_engine(admin_url.set(username=role, password=passwords[role]),
                                          pool_size=5, max_overflow=2, hide_parameters=True)
        yield engines
    finally:
        for engine in engines.values():
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            for role in passwords:
                connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        admin.dispose()


@pytest.fixture
def production_clients(release_database, monkeypatch):
    engines = release_database
    with engines["admin"].begin() as connection:
        tables = ",".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    for key, value in {"ENVIRONMENT": "production", "SERVICE_ROLE": "api", "COOKIE_SECURE": "true",
                       "WORKFLOW_WORKER_ENABLED": "false", "ALLOWED_ORIGINS": '["https://web.example"]',
                       "DATABASE_URL": engines["api"].url.render_as_string(hide_password=False),
                       "N8N_WEBHOOK_URL": "https://fictional.app.n8n.cloud/webhook/railway-test",
                       "N8N_WEBHOOK_TOKEN": "fictional-outbound-token",
                       "N8N_CALLBACK_TOKEN": "separate-callback-secret-0000000000"}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    from app import main
    monkeypatch.setattr(main, "engine", engines["api"])
    application = main.create_app()
    api_factory = sessionmaker(engines["api"], expire_on_commit=False)
    worker_factory = sessionmaker(engines["worker"], expire_on_commit=False)

    def override_db():
        with api_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    try:
        with TestClient(application, base_url="https://web.example", headers={"Origin": "https://web.example"}) as first, \
             TestClient(application, base_url="https://web.example", headers={"Origin": "https://web.example"}) as second:
            yield first, second, api_factory, worker_factory
    finally:
        get_settings.cache_clear()


def test_full_chain_startup_roles_and_default_deny(release_database):
    engines = release_database
    for role in ("api", "worker"):
        check_database(engines[role], role, production=True)
    with pytest.raises(RuntimeError):
        check_database(engines["admin"], "api", production=True)
    with engines["api"].connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_REVISION
        version_column = next(column for column in inspect(connection).get_columns("alembic_version")
                              if column["name"] == "version_num")
        assert version_column["type"].length == 64
        assert connection.scalar(text("SELECT count(*) FROM daily_metrics")) == 0
        with pytest.raises(DBAPIError):
            connection.execute(text("CREATE TABLE forbidden_ddl (id integer)"))


def test_production_auth_cookie_csrf_cors_and_shared_limits(production_clients):
    first, second, _, _ = production_clients
    workspace = register(first)
    cookie = first.cookies.get("marketmind_session")
    assert cookie
    assert first.get("/api/auth/me").status_code == 200
    registered = second.post("/api/auth/register", json={"email": "second@example.com", "password": "a-good-test-password",
                              "business_name": "Other", "industry": "ecommerce"})
    header = registered.headers["set-cookie"].lower()
    assert "httponly" in header and "secure" in header and "samesite=lax" in header and "domain=" not in header
    assert first.get("/api/business", headers={"X-Workspace-ID": registered.json()["workspace_id"]}).status_code == 403
    assert second.get("/api/business", headers={"X-Workspace-ID": workspace}).status_code == 403
    assert first.post("/api/auth/logout", headers={"Origin": "https://hostile.example"}).status_code == 403
    first.headers.pop("Origin")
    assert first.post("/api/auth/logout").status_code == 403
    first.headers["Origin"] = "https://web.example"
    cors = first.options("/api/business", headers={"Access-Control-Request-Method": "GET"})
    assert cors.headers["access-control-allow-origin"] == "https://web.example"
    assert first.post("/api/auth/logout").status_code == 204
    assert first.get("/api/auth/me").status_code == 401
    for _ in range(10):
        assert first.post("/api/auth/login", json={"email": "owner@example.com", "password": "incorrect-password"}).status_code == 401
    blocked = second.post("/api/auth/login", json={"email": "owner@example.com", "password": "a-good-test-password"})
    assert blocked.status_code == 429 and blocked.headers["retry-after"]


def test_rls_scopes_commits_pool_reuse_and_cross_tenant_writes(production_clients):
    first, second, api_factory, _ = production_clients
    workspace = register(first)
    other = register(second, "second@example.com")
    from tests.test_foundation import upload
    assert upload(first, "date,revenue,orders,ad_spend,cost_of_goods\n2026-01-01,100,10,10,20").status_code == 200
    with api_factory() as session:
        assert session.scalars(select(DailyMetric)).all() == []
        set_db_scope(session, workspace_id=workspace)
        assert len(session.scalars(select(DailyMetric)).all()) == 1
        session.commit()
        assert len(session.scalars(select(DailyMetric)).all()) == 1
        session.add(DailyMetric(workspace_id=other, day=datetime(2026, 1, 1).date(), values={}))
        with pytest.raises(DBAPIError):
            session.commit()
    with api_factory() as reused:
        assert reused.scalars(select(DailyMetric)).all() == []
        set_db_scope(reused, workspace_id=other)
        assert reused.scalars(select(DailyMetric)).all() == []


def test_source_bearer_bootstrap_uses_verified_source_workspace(production_clients):
    first, second, _, _ = production_clients
    workspace = register(first)
    other = register(second, "second@example.com")
    source = create_source(first, workspace, "fictional-sheet")
    foreign = create_source(second, other, "other-sheet")
    first.headers.pop("Origin")
    endpoint = f"/api/integrations/google-sheets/{source['id']}/ingest"
    assert first.post(endpoint, json=batch(ecom_records()), headers={
        "Authorization": f"Bearer {foreign['ingestion_token']}"}).status_code == 401
    result = first.post(endpoint, json=batch(ecom_records()), headers={
        "Authorization": f"Bearer {source['ingestion_token']}"})
    assert result.status_code == 200, result.text
    assert result.json()["accepted_count"] == 6
    assert second.get("/api/data-sources/quality").json()["reconciliation"]["accepted_events"] == 0


def test_restricted_worker_journey_approval_callback_and_learning(production_clients, monkeypatch):
    owner, outsider, _, worker_factory = production_clients
    workspace = register(owner)
    register(outsider, "outsider@example.com")
    profile(owner, monthly_budget="100.00", goals=["Improve profit"])
    from tests.test_foundation import upload
    fixture = Path(__file__).parents[2] / "examples/v1-ecommerce.csv"
    assert upload(owner, fixture.read_text()).status_code == 200

    def run(kind, payload, key):
        queued = owner.post("/api/workflow-jobs", json={"kind": kind, "payload": payload, "idempotency_key": key})
        assert queued.status_code == 202, queued.text
        processed = process_next_job(worker_factory, queued.json()["id"])
        assert processed and processed["status"] == "completed", processed
        return processed["result"]

    report = run("investigation", {"question": "Why is profit weak?"}, "release-investigation")["report"]
    strategy = run("growth_strategy", {"investigation_id": report["id"]}, "release-strategy")
    recommendation = strategy["recommendations"][0]
    assert create_design(owner, recommendation).status_code == 409
    assert approve(outsider, recommendation).status_code == 404
    assert approve(owner, recommendation).status_code == 200
    design = create_design(owner, recommendation).json()
    from app.integrations.n8n import DispatchOutcome
    monkeypatch.setattr("app.integrations.n8n.N8nExecutor.execute",
                        lambda *args, **kwargs: DispatchOutcome("acknowledged", 202))
    dispatch_response = owner.post(f"/api/experiments/{design['experiment_id']}/approve")
    assert dispatch_response.status_code == 200, dispatch_response.text
    dispatch = dispatch_response.json()
    body = callback_body(design, dispatch, callback_id="release-completed")
    body["workspace_id"] = workspace
    owner.headers.pop("Origin")
    assert post_callback(owner, body, token="wrong-token").status_code == 401
    invalid = dict(body, experiment_version=999)
    assert post_callback(owner, invalid).status_code == 404
    callback = post_callback(owner, body)
    assert callback.status_code == 200, callback.text
    evaluated = process_next_job(worker_factory, callback.json()["evaluation_job"]["id"])
    assert evaluated["status"] == "completed", evaluated
    assert post_callback(owner, body).json()["duplicate"] is True
    owner.headers["Origin"] = "https://web.example"
    history = owner.get(f"/api/experiments/{design['experiment_id']}/history").json()
    assert history["learning"]["content"]["real_business_measurement"] is False
    assert outsider.get(f"/api/experiments/{design['experiment_id']}/history").status_code == 404


def test_competing_workers_renewal_and_expired_writer_fence(production_clients, release_database, monkeypatch):
    owner, _, _, factory = production_clients
    workspace = register(owner)
    queued = owner.post("/api/workflow-jobs", json={"kind": "investigation", "payload": {"question": "Why?"},
                                                "idempotency_key": "competing-workers"}).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: _claim_job(factory, queued["id"]), range(2)))
    claimed = [claim for claim in claims if claim]
    assert len(claimed) == 1
    assert renew_lease(factory, workspace, queued["id"], claimed[0].lease_token)
    assert not renew_lease(factory, workspace, queued["id"], "wrong-token")
    with release_database["admin"].begin() as connection:
        connection.execute(text("UPDATE workflow_jobs SET lease_expires_at=:expired WHERE id=:id"),
                           {"expired": datetime.now(timezone.utc) - timedelta(seconds=1), "id": queued["id"]})
    _recover_expired(factory)
    # Pre-start recovery permits a safe retry, then simulate loss during the node.
    entered, release = threading.Event(), threading.Event()
    from app.api import investigation_agent
    original = investigation_agent.investigate
    monkeypatch.setenv("WORKER_HEARTBEAT_SECONDS", "1")
    get_settings.cache_clear()

    def slow(*args):
        entered.set()
        assert release.wait(15)
        return original(*args)

    monkeypatch.setattr(investigation_agent, "investigate", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        processing = pool.submit(process_next_job, factory, queued["id"])
        try:
            assert entered.wait(15)
            with release_database["admin"].connect() as connection:
                initial_expiry = connection.scalar(text("SELECT lease_expires_at FROM workflow_jobs WHERE id=:id"),
                                                    {"id": queued["id"]})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with release_database["admin"].connect() as connection:
                    renewed_expiry = connection.scalar(text("SELECT lease_expires_at FROM workflow_jobs WHERE id=:id"),
                                                       {"id": queued["id"]})
                if renewed_expiry > initial_expiry + timedelta(milliseconds=500):
                    break
                time.sleep(0.1)
            assert renewed_expiry > initial_expiry + timedelta(milliseconds=500)
            with release_database["admin"].begin() as connection:
                connection.execute(text("UPDATE workflow_jobs SET lease_expires_at=:expired WHERE id=:id"),
                                   {"expired": datetime.now(timezone.utc) - timedelta(seconds=1), "id": queued["id"]})
            _recover_expired(factory)
        finally:
            release.set()
        processing.result(timeout=20)
    with factory() as session:
        set_db_scope(session, workspace_id=workspace)
        job = session.get(WorkflowJob, queued["id"])
        assert job.status == "failed" and job.error_code == "worker_interrupted_during_step"
        assert not session.scalars(select(InvestigationRun)).all()


def test_standalone_worker_process_health_and_job_completion(production_clients, release_database, tmp_path):
    import socket
    import urllib.request

    owner, _, _, _ = production_clients
    register(owner)
    job = owner.post("/api/workflow-jobs", json={"kind": "investigation", "payload": {"question": "Why?"},
                                              "idempotency_key": "independent-worker"}).json()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ | {"SERVICE_ROLE": "worker", "PORT": str(port),
                        "DATABASE_URL": release_database["worker"].url.render_as_string(hide_password=False),
                        "WORKER_POLL_SECONDS": "0.1"}
    log_path = tmp_path / "worker.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=Path(__file__).parents[1],
                                   env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            healthy = False
            while time.monotonic() < deadline:
                assert process.poll() is None, "Worker exited before processing the fictional job"
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        healthy = response.status == 200
                except OSError:
                    pass
                if healthy and owner.get(f"/api/workflow-jobs/{job['id']}").json()["status"] == "completed":
                    break
                time.sleep(0.1)
            assert healthy
            assert owner.get(f"/api/workflow-jobs/{job['id']}").json()["status"] == "completed"
            assert process.poll() is None
        finally:
            process.terminate()
            process.wait(timeout=15)
    output = log_path.read_text()
    assert "worker_started" in output and "job_finished" in output
    for secret_name in ("JWT_SECRET", "N8N_WEBHOOK_TOKEN", "N8N_CALLBACK_TOKEN"):
        assert env[secret_name] not in output
