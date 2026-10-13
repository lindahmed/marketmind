from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.integrations.n8n import DispatchOutcome
from app.config import Settings
from app.main import app
from app.models import (AuditEvent, Experiment, ExperimentApproval, ExperimentEvaluation, ExperimentLearning,
                        N8nCallbackReceipt)
from app.workflow_jobs import process_next_job
from tests.conftest import register
from tests.test_growth_strategy import approve, create_design, generate, prepare


CALLBACK_URL = "/api/integrations/n8n/simulation-callback"


def test_callback_token_is_long_masked_and_distinct_from_outbound_secret():
    value = "a-strong-callback-secret-with-more-than-32-chars"
    settings = Settings(_env_file=None, jwt_secret="test-only-secret-with-at-least-32-characters",
                        n8n_webhook_url="https://marketmind.app.n8n.cloud/webhook/experiment",
                        n8n_webhook_token="a-different-outbound-secret-value",
                        n8n_callback_token=value)
    assert value not in repr(settings)
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(_env_file=None, jwt_secret="test-only-secret-with-at-least-32-characters",
                 n8n_callback_token="short")
    with pytest.raises(ValueError, match="different from N8N_WEBHOOK_TOKEN"):
        Settings(_env_file=None, jwt_secret="test-only-secret-with-at-least-32-characters",
                 n8n_webhook_url="https://marketmind.app.n8n.cloud/webhook/experiment",
                 n8n_webhook_token=value, n8n_callback_token=value)


def configure_callback(monkeypatch):
    monkeypatch.setattr("app.callback_api.get_settings",
                        lambda: SimpleNamespace(n8n_callback_token=SecretStr("separate-callback-secret-0000000000")))


def approved_design(client, monkeypatch):
    workspace, report = prepare(client)
    recommendation = next(row for row in generate(client, report)["recommendations"]
                          if row["content"]["success_metric"] == "estimated_profit")
    assert approve(client, recommendation).status_code == 200
    design_response = create_design(client, recommendation)
    assert design_response.status_code == 201, design_response.text
    design = design_response.json()

    class Executor:
        def execute(self, *_):
            return DispatchOutcome("acknowledged", 202)

    monkeypatch.setattr("app.api.configured_n8n_executor", lambda db: Executor())
    dispatch = client.post(f"/api/experiments/{design['experiment_id']}/approve")
    assert dispatch.status_code == 200, dispatch.text
    return workspace, design, dispatch.json()


def callback_body(design, dispatch, callback_id="callback-001", **changes):
    plan = design["design"]
    metric = plan["success_metrics"][0]
    baseline_end = date.fromisoformat(plan["baseline"]["end"])
    start = baseline_end + timedelta(days=1)
    end = start + timedelta(days=plan["duration_days"] - 1)
    guard = plan["evaluation_criteria"]["profit_guardrail"]
    metrics = {metric["metric"]: metric["target"], "estimated_profit": str(Decimal(guard["minimum"]) + 1)}
    if metric["metric"] == "estimated_profit":
        metrics["estimated_profit"] = metric["target"]
    return {"callback_id": callback_id, "workspace_id": "", "experiment_id": design["experiment_id"],
            "experiment_version": design["experiment_version"], "approval_id": dispatch["approval_id"],
            "execution_id": dispatch["execution_id"], "event": "experiment.simulation.completed",
            "mode": "simulation_only", "result": {"data_origin": "simulated", "period_start": str(start),
                "period_end": str(end), "observed_days": plan["duration_days"], "missing_days": 0,
                "financial_data_complete": True, "volume": plan["evaluation_criteria"]["minimum_volume"],
                "metrics": metrics}, **changes}


def post_callback(client, body, token="separate-callback-secret-0000000000"):
    return client.post(CALLBACK_URL, json=body, headers={"Authorization": f"Bearer {token}"})


def finish_evaluation(response):
    evaluation_job_id = response.json()["evaluation_job"]["id"]
    result = process_next_job(app.state.test_session_factory, evaluation_job_id)
    assert result["status"] == "completed"
    return result


def test_callback_evaluates_simulation_persists_learning_and_reuses_it_in_investigation(clients, monkeypatch):
    client, other = clients
    workspace, design, dispatch = approved_design(client, monkeypatch)
    other_workspace = register(other, "other@example.com")
    configure_callback(monkeypatch)
    body = callback_body(design, dispatch)
    body["workspace_id"] = workspace

    response = post_callback(client, body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["experiment_status"] == "completed"
    assert result["dispatch_status"] == "completed"
    assert result["completion_status"] == "completed"
    assert result["evaluation"] is None
    assert result["evaluation_job"]["status"] == "queued"
    finish_evaluation(response)
    repeated_approval = client.post(f"/api/experiments/{design['experiment_id']}/approve")
    assert repeated_approval.status_code == 200
    assert repeated_approval.json()["execution_id"] == dispatch["execution_id"]
    assert repeated_approval.json()["dispatch_status"] == "completed"
    assert other.get(f"/api/experiments/{design['experiment_id']}/history").status_code == 404
    history = client.get(f"/api/experiments/{design['experiment_id']}/history").json()
    assert history["learning"]["content"]["evidence_ids"] == design["design"]["evidence_ids"]
    assert history["evaluation"]["classification"] == "simulation_met_criteria"
    assert client.get("/api/experiments").json()[0]["evaluation"]["simulation_only"] is True

    later = client.post("/api/investigations", json={"question": "How did the profit experiment go?"})
    assert later.status_code == 201, later.text
    memories = [item for item in later.json()["result"]["findings"] if item["kind"] == "prior_experiment_learning"]
    assert memories and memories[0]["source_id"] == f"learning:{design['experiment_id']}"
    assert "not a real business measurement" in memories[0]["evidence"]
    assert other_workspace != workspace
    with app.state.test_session_factory() as db:
        assert len(db.scalars(select(N8nCallbackReceipt).where(N8nCallbackReceipt.workspace_id == workspace)).all()) == 1
        assert len(db.scalars(select(ExperimentEvaluation).where(ExperimentEvaluation.workspace_id == workspace)).all()) == 1
        assert len(db.scalars(select(ExperimentLearning).where(ExperimentLearning.workspace_id == workspace)).all()) == 1


def test_callback_duplicate_replay_and_different_second_completion_are_rejected(clients, monkeypatch):
    client, _ = clients
    workspace, design, dispatch = approved_design(client, monkeypatch)
    configure_callback(monkeypatch)
    body = callback_body(design, dispatch)
    body["workspace_id"] = workspace
    first = post_callback(client, body)
    assert first.status_code == 200, first.text
    finish_evaluation(first)

    replay = post_callback(client, body)
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    different_completion = {**body, "callback_id": "callback-002"}
    assert post_callback(client, different_completion).status_code == 409
    changed_replay = {**body, "result": {**body["result"], "volume": body["result"]["volume"] + 1}}
    assert post_callback(client, changed_replay).status_code == 409
    with app.state.test_session_factory() as db:
        events = db.scalars(select(AuditEvent.action).where(
            AuditEvent.workspace_id == workspace, AuditEvent.resource_id == design["experiment_id"])).all()
        assert events.count("experiment.callback_replayed") == 1
        assert events.count("experiment.callback_duplicate_completion") == 1
        assert len(db.scalars(select(ExperimentEvaluation).where(
            ExperimentEvaluation.experiment_id == design["experiment_id"])).all()) == 1


def test_callback_requires_secret_and_matching_tenant_relationship(clients, monkeypatch):
    client, other = clients
    workspace, design, dispatch = approved_design(client, monkeypatch)
    other_workspace = register(other, "other@example.com")
    configure_callback(monkeypatch)
    body = callback_body(design, dispatch)
    body["workspace_id"] = workspace
    assert post_callback(client, body, token="wrong-secret").status_code == 401
    foreign_claim = {**body, "workspace_id": other_workspace, "callback_id": "foreign-workspace-event"}
    assert post_callback(client, foreign_claim).status_code == 404
    assert client.get("/api/experiments").json()[0]["status"] == "approved"
    with app.state.test_session_factory() as db:
        experiment = db.get(Experiment, design["experiment_id"])
        assert experiment.status == "approved"
        assert db.scalars(select(N8nCallbackReceipt)).all() == []


def test_failed_callback_is_terminal_and_has_an_inconclusive_evaluation(clients, monkeypatch):
    client, _ = clients
    workspace, design, dispatch = approved_design(client, monkeypatch)
    configure_callback(monkeypatch)
    body = {"callback_id": "callback-failed", "workspace_id": workspace,
            "experiment_id": design["experiment_id"], "experiment_version": design["experiment_version"],
            "approval_id": dispatch["approval_id"], "execution_id": dispatch["execution_id"],
            "event": "experiment.simulation.failed", "mode": "simulation_only", "failure_code": "scenario_error"}
    response = post_callback(client, body)
    assert response.status_code == 200, response.text
    assert response.json()["experiment_status"] == "execution_failed"
    finish_evaluation(response)
    report = client.get(f"/api/experiments/{design['experiment_id']}/history").json()["evaluation"]["report"]
    assert report["data_quality"]["reasons"] == ["simulation_execution_failed"]
    repeated = client.post(f"/api/experiments/{design['experiment_id']}/approve")
    assert repeated.status_code == 200
    assert repeated.json()["dispatch_status"] == "execution_failed"


def test_incomplete_simulation_window_is_inconclusive_not_success(clients, monkeypatch):
    client, _ = clients
    workspace, design, dispatch = approved_design(client, monkeypatch)
    configure_callback(monkeypatch)
    body = callback_body(design, dispatch, callback_id="callback-inconclusive")
    body["workspace_id"] = workspace
    body["result"]["missing_days"] = 2
    response = post_callback(client, body)
    assert response.status_code == 200, response.text
    finish_evaluation(response)
    evaluation = client.get(f"/api/experiments/{design['experiment_id']}/history").json()["evaluation"]
    report = evaluation["report"]
    assert evaluation["classification"] == "inconclusive"
    assert "incomplete_or_short_measurement_window" in report["data_quality"]["reasons"]
    assert report["actual_profit_improvement_verified"] is False


def test_evaluation_worker_revalidates_saved_approval(clients, monkeypatch):
    client, _ = clients
    workspace, design, dispatch = approved_design(client, monkeypatch)
    configure_callback(monkeypatch)
    body = callback_body(design, dispatch, callback_id="callback-approval-recheck")
    body["workspace_id"] = workspace
    response = post_callback(client, body)
    assert response.status_code == 200
    job_id = response.json()["evaluation_job"]["id"]
    with app.state.test_session_factory.begin() as db:
        approval = db.get(ExperimentApproval, dispatch["approval_id"])
        approval.status = "revoked"
    result = process_next_job(app.state.test_session_factory, job_id)
    assert result["status"] == "failed"
    assert result["error_code"] == "evaluation_approval_or_tenant_revalidation_failed"
    history = client.get(f"/api/experiments/{design['experiment_id']}/history").json()
    assert history["evaluation"] is None
    assert history["learning"] is None
