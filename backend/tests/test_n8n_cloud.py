import json
from datetime import datetime, timezone
import urllib.error

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.config import Settings
from app.integrations.n8n import DispatchOutcome, NoRedirect, N8nExecutor
from app.models import AuditEvent, Experiment, ExperimentApproval, Membership, N8nDispatch, User, Workspace
from app.main import app
from tests.conftest import register


class AllowApproval:
    def require_approved(self, workspace_id, experiment_id, approval_id):
        assert workspace_id == "workspace-a"
        assert experiment_id == "experiment-a"
        assert approval_id == "approval-a"


def test_n8n_executor_sends_minimal_simulation_and_treats_2xx_as_ack(monkeypatch):
    captured = {}

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class Opener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setattr("app.integrations.n8n.urllib.request.build_opener", lambda *_: Opener())
    executor = N8nExecutor("https://marketmind.app.n8n.cloud/webhook/marketmind-experiment", "private-token",
                           AllowApproval(), timeout=9)
    outcome = executor.execute(
        type("Context", (), {"workspace_id": "workspace-a"})(), "experiment-a", "approval-a", 3, "execution-a",
        "simulation_only", {"scenario": "conversion_lift"}, "workspace-a:experiment-a:v3",
        datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    assert outcome == DispatchOutcome("acknowledged", 202)
    assert captured["timeout"] == 9
    assert captured["headers"]["Authorization"] == "Bearer private-token"
    assert captured["headers"]["Idempotency-key"] == "workspace-a:experiment-a:v3"
    assert captured["payload"] == {
        "schema_version": 1, "event": "experiment.approved", "workspace_id": "workspace-a",
        "experiment_id": "experiment-a", "experiment_version": 3, "approval_id": "approval-a",
        "execution_id": captured["payload"]["execution_id"], "approved_action_type": "simulation_only",
        "mode": "simulation_only", "metadata": {"scenario": "conversion_lift"},
        "idempotency_key": "workspace-a:experiment-a:v3", "approved_at": "2026-10-12T00:00:00+00:00",
    }


@pytest.mark.parametrize("url", [
    "http://marketmind.app.n8n.cloud/webhook/marketmind-experiment",
    "https://example.com/webhook/marketmind-experiment",
    "https://marketmind.app.n8n.cloud/webhook/marketmind-experiment?token=secret",
    "https://marketmind.app.n8n.cloud.evil.test/webhook/marketmind-experiment",
])
def test_n8n_executor_rejects_non_cloud_or_insecure_urls(url):
    with pytest.raises(ValueError):
        N8nExecutor(url, "private-token", AllowApproval())


def test_n8n_executor_rejects_unapproved_action_and_never_follows_redirects(monkeypatch):
    monkeypatch.setattr("app.integrations.n8n.urllib.request.build_opener",
                        lambda *_: pytest.fail("invalid action must not reach the webhook"))
    executor = N8nExecutor("https://marketmind.app.n8n.cloud/webhook/marketmind-experiment",
                           "private-token", AllowApproval())
    with pytest.raises(ValueError, match="simulation-only"):
        executor.execute(type("Context", (), {"workspace_id": "workspace-a"})(), "experiment-a",
            "approval-a", 1, "execution-a", "send_email", {"scenario": "conversion_lift"},
            "workspace-a:experiment-a:v1", datetime.now(timezone.utc))
    assert NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.test/") is None


def test_n8n_executor_checks_approval_before_network(monkeypatch):
    class DenyApproval:
        def require_approved(self, *_):
            raise PermissionError("denied")

    monkeypatch.setattr("app.integrations.n8n.urllib.request.build_opener",
                        lambda *_: pytest.fail("webhook must not be called"))
    executor = N8nExecutor("https://marketmind.app.n8n.cloud/webhook/marketmind-experiment",
                           "private-token", DenyApproval())
    with pytest.raises(PermissionError):
        executor.execute(type("Context", (), {"workspace_id": "workspace-a"})(), "experiment-a",
                         "approval-a", 1, "execution-a", "simulation_only", {"scenario": "conversion_lift"},
                         "workspace-a:experiment-a:v1", datetime.now(timezone.utc))


@pytest.mark.parametrize(("failure", "expected"), [
    (urllib.error.HTTPError("https://marketmind.app.n8n.cloud/webhook/x", 503, "unavailable", {}, None),
     DispatchOutcome("failed", 503, "http_5xx")),
    (urllib.error.URLError("network unavailable"), DispatchOutcome("failed", None, "network_error")),
])
def test_n8n_executor_records_safe_http_and_network_failures(monkeypatch, failure, expected):
    class Opener:
        def open(self, *_args, **_kwargs):
            raise failure

    monkeypatch.setattr("app.integrations.n8n.urllib.request.build_opener", lambda *_: Opener())
    executor = N8nExecutor("https://marketmind.app.n8n.cloud/webhook/marketmind-experiment",
                           "private-token", AllowApproval())
    result = executor.execute(type("Context", (), {"workspace_id": "workspace-a"})(),
        "experiment-a", "approval-a", 1, "execution-a", "simulation_only",
        {"scenario": "conversion_lift"}, "workspace-a:experiment-a:v1", datetime.now(timezone.utc))
    assert result == expected


def test_n8n_secret_is_masked_and_requires_a_matching_webhook_url():
    configured = Settings(_env_file=None, jwt_secret="test-only-secret-with-at-least-32-characters",
        n8n_webhook_url="https://marketmind.app.n8n.cloud/webhook/marketmind-experiment",
        n8n_webhook_token="example-webhook-secret")
    assert isinstance(configured.n8n_webhook_token, SecretStr)
    assert "example-webhook-secret" not in repr(configured)
    with pytest.raises(ValidationError, match="Configure both N8N_WEBHOOK_URL"):
        Settings(_env_file=None, jwt_secret="test-only-secret-with-at-least-32-characters",
                 n8n_webhook_url="https://marketmind.app.n8n.cloud/webhook/marketmind-experiment")


def test_experiment_approval_dispatch_is_owner_scoped_and_idempotent(clients, monkeypatch):
    first, second = clients
    workspace_id = register(first)
    register(second, "second@example.com")
    calls = []

    class FakeExecutor:
        def execute(self, context, experiment_id, approval_id, version, execution_id,
                    action_type, metadata, idempotency_key, approved_at):
            calls.append((experiment_id, approval_id, execution_id, idempotency_key))
            assert context.workspace_id == workspace_id
            assert action_type == "simulation_only"
            assert metadata == {"scenario": "conversion_lift"}
            return DispatchOutcome("acknowledged", 200)

    monkeypatch.setattr("app.api.configured_n8n_executor", lambda db: FakeExecutor())
    experiment = first.post("/api/experiments", json={"name": "Conversion baseline simulation",
        "action_type": "simulation_only", "metadata": {"scenario": "conversion_lift"}})
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]
    first_dispatch = first.post(f"/api/experiments/{experiment_id}/approve")
    assert first_dispatch.status_code == 200
    result = first_dispatch.json()
    assert result["dispatch_status"] == "acknowledged"
    assert result["experiment_status"] == "approved"
    assert result["completion_status"] == "not_reported"
    duplicate = first.post(f"/api/experiments/{experiment_id}/approve")
    assert duplicate.status_code == 200
    assert duplicate.json()["execution_id"] == result["execution_id"]
    assert len(calls) == 1
    assert second.post(f"/api/experiments/{experiment_id}/approve").status_code == 404
    assert len(calls) == 1
    with app.state.test_session_factory() as db:
        second_user = db.scalar(select(User).where(User.email == "second@example.com"))
        db.add(Membership(user_id=second_user.id, workspace_id=workspace_id, role="analyst"))
        db.commit()
    assert second.post(f"/api/experiments/{experiment_id}/approve",
                       headers={"X-Workspace-ID": workspace_id}).status_code == 403
    assert len(calls) == 1
    with app.state.test_session_factory() as db:
        actions = db.scalars(select(AuditEvent.action).where(AuditEvent.workspace_id == workspace_id)).all()
    assert "experiment.created" in actions
    assert "experiment.approved" in actions
    assert "n8n.dispatch_started" in actions
    assert "n8n.webhook_acknowledged" in actions
    assert "n8n.dispatch_duplicate" in actions


def test_failed_webhook_dispatch_is_saved_and_never_resent(clients, monkeypatch):
    client, _ = clients
    workspace_id = register(client)
    calls = []

    class FailedExecutor:
        def execute(self, *_):
            calls.append(True)
            return DispatchOutcome("failed", 503, "http_5xx")

    monkeypatch.setattr("app.api.configured_n8n_executor", lambda db: FailedExecutor())
    experiment = client.post("/api/experiments", json={"name": "Repeat booking simulation",
        "action_type": "simulation_only", "metadata": {"scenario": "repeat_booking"}}).json()
    failed = client.post(f"/api/experiments/{experiment['id']}/approve").json()
    assert failed["dispatch_status"] == "failed"
    assert failed["failure_code"] == "http_5xx"
    assert failed["completion_status"] == "not_reported"
    again = client.post(f"/api/experiments/{experiment['id']}/approve").json()
    assert again["execution_id"] == failed["execution_id"]
    assert again["dispatch_status"] == "failed"
    assert len(calls) == 1
    with app.state.test_session_factory() as db:
        actions = db.scalars(select(AuditEvent.action).where(AuditEvent.workspace_id == workspace_id)).all()
    assert "n8n.webhook_failed" in actions


def test_explicit_no_automation_constraint_blocks_approval_before_dispatch(clients, monkeypatch):
    client, _ = clients
    workspace_id = register(client)
    calls = []

    class ForbiddenExecutor:
        def execute(self, *_):
            calls.append(True)
            return DispatchOutcome("acknowledged", 200)

    monkeypatch.setattr("app.api.configured_n8n_executor", lambda db: ForbiddenExecutor())
    experiment = client.post("/api/experiments", json={"name": "Reminder simulation",
        "action_type": "simulation_only", "metadata": {"scenario": "reminder_timing"}}).json()
    with app.state.test_session_factory() as db:
        workspace = db.get(Workspace, workspace_id)
        workspace.constraints = ["No automation before manager review"]
        db.commit()
    blocked = client.post(f"/api/experiments/{experiment['id']}/approve")
    assert blocked.status_code == 409
    assert calls == []
    with app.state.test_session_factory() as db:
        actions = db.scalars(select(AuditEvent.action).where(AuditEvent.workspace_id == workspace_id)).all()
    assert "experiment.approval_blocked" in actions


def test_create_experiment_rejects_unapproved_action_or_unsafe_metadata(clients):
    client, _ = clients
    register(client)
    config = client.get("/api/knowledge/retrieval").json()
    assert "n8n_webhook_token" not in config and "n8n_webhook_url" not in config
    assert client.post("/api/experiments", json={"name": "External campaign", "action_type": "send_email",
        "metadata": {"scenario": "conversion_lift"}}).status_code == 422
    assert client.post("/api/experiments", json={"name": "External campaign", "action_type": "simulation_only",
        "metadata": {"scenario": "conversion_lift", "customer_email": "person@example.com"}}).status_code == 422


def test_owner_can_reject_a_simulation_draft_without_dispatch(clients, monkeypatch):
    client, other = clients
    workspace_id = register(client)
    register(other, "other@example.com")
    experiment = client.post("/api/experiments", json={"name": "Review checkout simulation",
        "action_type": "simulation_only", "metadata": {"scenario": "conversion_lift"}}).json()
    monkeypatch.setattr("app.api.configured_n8n_executor",
                        lambda db: pytest.fail("Rejecting a draft must not dispatch it"))
    rejected = client.post(f"/api/experiments/{experiment['id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.post(f"/api/experiments/{experiment['id']}/approve").status_code == 409
    assert other.post(f"/api/experiments/{experiment['id']}/reject").status_code == 404
    with app.state.test_session_factory() as db:
        assert db.scalars(select(N8nDispatch).where(N8nDispatch.workspace_id == workspace_id)).all() == []
        assert "experiment.rejected" in db.scalars(select(AuditEvent.action).where(
            AuditEvent.workspace_id == workspace_id)).all()


def test_database_approval_verifier_checks_workspace_owner_version_and_state():
    from app.integrations.n8n import DatabaseApprovalVerifier

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            owner = User(email="owner@example.com", password_hash="test")
            other = User(email="other@example.com", password_hash="test")
            workspace = Workspace(name="Store", industry="ecommerce")
            other_workspace = Workspace(name="Other Store", industry="ecommerce")
            db.add_all([owner, other, workspace, other_workspace])
            db.flush()
            db.add_all([Membership(user_id=owner.id, workspace_id=workspace.id, role="owner"),
                        Membership(user_id=other.id, workspace_id=other_workspace.id, role="owner")])
            experiment = Experiment(workspace_id=workspace.id, created_by_user_id=owner.id, name="Simulation",
                                    action_type="simulation_only", status="approved", version=1,
                                    metadata_json={"scenario": "conversion_lift"})
            db.add(experiment)
            db.flush()
            approval = ExperimentApproval(workspace_id=workspace.id, experiment_id=experiment.id,
                experiment_version=1, approved_by_user_id=owner.id, status="approved")
            db.add(approval)
            db.commit()
            verifier = DatabaseApprovalVerifier(db)
            verifier.require_approved(workspace.id, experiment.id, approval.id)
            with pytest.raises(PermissionError):
                verifier.require_approved(other_workspace.id, experiment.id, approval.id)
            experiment.status = "draft"
            db.commit()
            with pytest.raises(PermissionError):
                verifier.require_approved(workspace.id, experiment.id, approval.id)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
