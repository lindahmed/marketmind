"""V1 fictional business journeys through real services and durable graphs.

Only the external n8n HTTP transport is substituted. No agent output is mocked.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.intelligence.evaluation import EvaluationAgent
from app.main import app
from app.models import ExperimentLearning, N8nDispatch
from app.workflow_jobs import process_next_job
from tests.conftest import register
from tests.test_experiment_feedback import callback_body, post_callback
from tests.test_foundation import upload
from tests.test_growth_strategy import approve, create_design, profile


@pytest.mark.parametrize("industry,metric", [
    ("ecommerce", "estimated_profit"), ("appointments", "completion_rate"),
])
@pytest.mark.parametrize("outcome", ["success", "failure", "inconclusive"])
def test_v1_complete_fictional_business_journey(clients, monkeypatch, industry, metric, outcome):
    owner, outsider = clients
    workspace = register(owner, f"demo-{industry}@example.com", industry)
    register(outsider, "outsider@example.com", industry)
    assert owner.post("/api/auth/logout").status_code == 204
    assert owner.get("/api/business").status_code == 401
    assert owner.post("/api/auth/login", json={
        "email": f"demo-{industry}@example.com", "password": "a-good-test-password",
    }).status_code == 200
    profile(owner, monthly_budget="100.00", goals=["Improve profit", "Improve completion"])
    fixture = Path(__file__).resolve().parents[2] / "examples" / f"v1-{industry}.csv"
    imported = upload(owner, fixture.read_text(encoding="utf-8"))
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported_rows"] == 14
    baseline_kpis = owner.get("/api/dashboard").json()["kpis"]
    assert outsider.get("/api/dashboard").json()["row_count"] == 0
    note = owner.post("/api/knowledge/documents", files={"file": (
        "fictional-notes.md", b"Fictional business: profit and completion need review. No proven cause yet.",
        "text/markdown",
    )})
    assert note.status_code == 201, note.text

    def run_job(kind, payload, key):
        queued = owner.post("/api/workflow-jobs", json={
            "kind": kind, "payload": payload, "idempotency_key": key,
        })
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["id"]
        assert outsider.get(f"/api/workflow-jobs/{job_id}").status_code == 404
        processed = process_next_job(app.state.test_session_factory, job_id)
        assert processed["status"] == "completed", processed
        return owner.get(f"/api/workflow-jobs/{job_id}").json()["result"]

    report = run_job("investigation", {"question": "Why are profit and completion weak?"},
                     "v1-investigation")["report"]
    assert report["model"] is None and report["status"] == "evidence_ready"
    assert report["result"]["evidence_sources"]
    strategy = run_job("growth_strategy", {"investigation_id": report["id"]}, "v1-strategy")
    recommendation = next(row for row in strategy["recommendations"]
                          if row["content"]["success_metric"] == metric)
    assert recommendation["content"]["evidence_ids"]
    assert recommendation["source_type"] == "industry_rule"
    assert create_design(owner, recommendation).status_code == 409
    assert approve(outsider, recommendation).status_code == 404
    assert approve(owner, recommendation).status_code == 200
    designed = create_design(owner, recommendation)
    assert designed.status_code == 201, designed.text
    design = designed.json()
    experiment_id = design["experiment_id"]
    with app.state.test_session_factory() as db:
        assert db.scalars(select(N8nDispatch)).all() == []

    settings = Settings(_env_file=None, jwt_secret="v1-test-session-secret-over-32-characters",
                        n8n_webhook_url="https://fictional.app.n8n.cloud/webhook/v1-demo",
                        n8n_webhook_token="fictional-outbound-token",
                        n8n_callback_token="separate-callback-secret-0000000000")
    monkeypatch.setattr("app.api.get_settings", lambda: settings)
    monkeypatch.setattr("app.callback_api.get_settings", lambda: settings)
    requests = []

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class Opener:
        def open(self, request, timeout):
            assert request.get_header("Authorization") == "Bearer fictional-outbound-token"
            requests.append(json.loads(request.data))
            return Response()

    monkeypatch.setattr("app.integrations.n8n.urllib.request.build_opener", lambda *_: Opener())
    assert outsider.post(f"/api/experiments/{experiment_id}/approve").status_code == 404
    receipt = owner.post(f"/api/experiments/{experiment_id}/approve")
    assert receipt.status_code == 200, receipt.text
    dispatch = receipt.json()
    assert dispatch["dispatch_status"] == "acknowledged"
    assert dispatch["completion_status"] == "not_reported"
    assert owner.get(f"/api/experiments/{experiment_id}/history").json()["evaluation"] is None
    assert owner.post(f"/api/experiments/{experiment_id}/approve").json()["execution_id"] == dispatch["execution_id"]
    assert len(requests) == 1
    assert requests[0]["workspace_id"] == workspace
    assert requests[0]["mode"] == "simulation_only"
    assert requests[0]["approved_action_type"] == "simulation_only"
    body = callback_body(design, dispatch, callback_id=f"v1-{industry}-{outcome}")
    body["workspace_id"] = workspace
    if outcome == "failure":
        body["event"] = "experiment.simulation.failed"
        body.pop("result")
        body["failure_code"] = "scenario_error"
    elif outcome == "inconclusive":
        body["result"]["financial_data_complete"] = False
    assert post_callback(owner, body, token="wrong-token").status_code == 401
    callback = post_callback(owner, body)
    assert callback.status_code == 200, callback.text
    processed = process_next_job(app.state.test_session_factory, callback.json()["evaluation_job"]["id"])
    assert processed["status"] == "completed", processed
    assert post_callback(owner, body).json()["duplicate"] is True
    history = owner.get(f"/api/experiments/{experiment_id}/history").json()
    expected = "simulation_met_criteria" if outcome == "success" else "inconclusive"
    assert history["evaluation"]["classification"] == expected
    assert history["evaluation"]["report"]["actual_profit_improvement_verified"] is False
    assert history["learning"]["content"]["real_business_measurement"] is False
    assert history["history"]
    assert outsider.get(f"/api/experiments/{experiment_id}/history").status_code == 404
    assert owner.get("/api/dashboard").json()["kpis"] == baseline_kpis
    with app.state.test_session_factory() as db:
        assert len(db.scalars(select(ExperimentLearning).where(
            ExperimentLearning.workspace_id == workspace)).all()) == 1
    later = run_job("investigation", {"question": "What did the profit and completion simulation teach?"},
                    "v1-learning-review")["report"]
    learning = [row for row in later["result"]["findings"] if row["kind"] == "prior_experiment_learning"]
    assert learning and "not a real business measurement" in learning[0]["evidence"]


def test_missing_simulation_result_is_inconclusive():
    report = EvaluationAgent().evaluate({}, "completed", None)
    assert report["classification"] == "inconclusive"
    assert report["data_quality"]["reasons"] == ["simulation_result_missing"]
    assert report["actual_profit_improvement_verified"] is False
