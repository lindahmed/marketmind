from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.intelligence.checkpoint_store import TenantCheckpointSaver
from app.main import app
from app.models import InvestigationRun, WorkflowCheckpoint, WorkflowJob
from app.workflow_jobs import _compiled_job_graph, process_next_job
from tests.conftest import register
from tests.test_growth_strategy import prepare


def create_investigation_job(client, key="investigation-request-0001", question="Why did sales change?"):
    return client.post("/api/workflow-jobs", json={
        "kind": "investigation", "payload": {"question": question}, "idempotency_key": key,
    })


def test_investigation_job_is_durable_checkpointed_and_idempotent(clients):
    client, other = clients
    workspace = register(client)
    other_workspace = register(other, "other@example.com")
    response = create_investigation_job(client)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "queued"
    repeated = create_investigation_job(client)
    assert repeated.json()["id"] == job["id"] and repeated.json()["duplicate"] is True
    conflict = create_investigation_job(client, question="Different question?")
    assert conflict.status_code == 409

    completed = process_next_job(app.state.test_session_factory, job["id"])
    assert completed["status"] == "completed", completed.get("error_code")
    report = completed["result"]["report"]
    assert report["question"] == "Why did sales change?"
    assert process_next_job(app.state.test_session_factory, job["id"]) is None
    assert client.get(f"/api/workflow-jobs/{job['id']}").json()["status"] == "completed"
    assert other.get(f"/api/workflow-jobs/{job['id']}").status_code == 404
    with app.state.test_session_factory() as db:
        saved_job = db.get(WorkflowJob, job["id"])
        assert saved_job.workspace_id == workspace
        assert db.scalar(select(func.count()).select_from(InvestigationRun).where(
            InvestigationRun.job_id == job["id"], InvestigationRun.workspace_id == workspace,
        )) == 1
        checkpoints = db.scalars(select(WorkflowCheckpoint).where(
            WorkflowCheckpoint.workspace_id == workspace, WorkflowCheckpoint.job_id == job["id"],
        )).all()
        assert checkpoints
        assert not db.scalars(select(WorkflowCheckpoint).where(
            WorkflowCheckpoint.workspace_id == other_workspace, WorkflowCheckpoint.job_id == job["id"],
        )).all()
        latest = TenantCheckpointSaver(app.state.test_session_factory).get_tuple({"configurable": {
            "workspace_id": workspace, "thread_id": job["id"], "checkpoint_ns": "",
        }})
        assert latest is not None
        assert TenantCheckpointSaver(app.state.test_session_factory).get_tuple({"configurable": {
            "workspace_id": other_workspace, "thread_id": job["id"], "checkpoint_ns": "",
        }}) is None


def test_safe_prestart_retry_and_checkpoint_resume_after_restart(clients):
    client, _ = clients
    workspace = register(client)
    response = create_investigation_job(client, key="restart-request-0001")
    job_id = response.json()["id"]

    # A process that dies after claiming but before entering the graph may safely retry.
    with app.state.test_session_factory.begin() as db:
        row = db.get(WorkflowJob, job_id)
        row.status = "running"
        row.attempts = 1
        row.current_step = "claimed"
        row.lease_token = "expired-claim"
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    result = process_next_job(app.state.test_session_factory, job_id)
    assert result["status"] == "completed"
    assert result["attempts"] == 2

    # Simulate a restart after the graph node committed its result/checkpoint but
    # before the worker marked the persistent job completed.
    second = create_investigation_job(client, key="checkpoint-resume-0001")
    resume_id = second.json()["id"]
    with app.state.test_session_factory.begin() as db:
        row = db.get(WorkflowJob, resume_id)
        row.status = "running"
        row.attempts = 1
        row.current_step = "workflow"
        row.lease_token = "expired-workflow"
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        initial = {"job_id": row.id, "workspace_id": row.workspace_id,
                   "requested_by_user_id": row.requested_by_user_id,
                   "kind": row.kind, "payload": row.payload}
        config = {"configurable": {"thread_id": row.id, "workspace_id": row.workspace_id, "checkpoint_ns": ""}}
    _compiled_job_graph(app.state.test_session_factory).invoke(initial, config=config)
    assert process_next_job(app.state.test_session_factory, resume_id) is None
    with app.state.test_session_factory() as db:
        resumed = db.get(WorkflowJob, resume_id)
        assert resumed.status == "completed"
        assert resumed.result["report"]["question"] == "Why did sales change?"
        assert db.scalar(select(func.count()).select_from(InvestigationRun).where(
            InvestigationRun.job_id == resume_id, InvestigationRun.workspace_id == workspace,
        )) == 1


def test_worker_revalidates_membership_before_running(clients):
    client, _ = clients
    workspace = register(client)
    response = create_investigation_job(client, key="revoked-access-0001")
    job_id = response.json()["id"]
    with app.state.test_session_factory.begin() as db:
        from app.models import Membership
        membership = db.scalar(select(Membership).where(Membership.workspace_id == workspace))
        db.delete(membership)
    result = process_next_job(app.state.test_session_factory, job_id)
    assert result["status"] == "failed"
    assert result["error_code"] == "requester_access_revoked"
    with app.state.test_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(InvestigationRun).where(
            InvestigationRun.job_id == job_id,
        )) == 0


def test_worker_persists_safe_failure_state_for_agent_error(clients, monkeypatch):
    client, _ = clients
    register(client)
    response = create_investigation_job(client, key="provider-failure-0001")
    job_id = response.json()["id"]

    def fail(*_):
        from app.intelligence.investigation import InvestigationError
        raise InvestigationError("provider response contains sensitive prompt details")

    monkeypatch.setattr("app.api.investigation_agent.investigate", fail)
    result = process_next_job(app.state.test_session_factory, job_id)
    assert result["status"] == "failed"
    assert result["error_code"] == "investigation_provider_or_validation_failed"
    assert "sensitive" not in str(result)


def test_queued_job_can_be_cancelled_before_execution(clients):
    client, _ = clients
    register(client)
    job = create_investigation_job(client, key="cancel-before-start-0001").json()
    cancelled = client.post(f"/api/workflow-jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert process_next_job(app.state.test_session_factory, job["id"]) is None


def test_growth_strategy_runs_as_a_tenant_scoped_background_job(clients):
    client, other = clients
    _, report = prepare(client)
    register(other, "other@example.com")
    job_response = client.post("/api/workflow-jobs", json={
        "kind": "growth_strategy", "payload": {"investigation_id": report["id"]},
        "idempotency_key": "growth-strategy-request-001",
    })
    assert job_response.status_code == 202, job_response.text
    job = job_response.json()
    assert other.get(f"/api/workflow-jobs/{job['id']}").status_code == 404
    completed = process_next_job(app.state.test_session_factory, job["id"])
    assert completed["status"] == "completed", completed.get("error_code")
    assert completed["result"]["recommendations"]
    listed = client.get("/api/growth/recommendations", params={"investigation_id": report["id"]})
    assert listed.status_code == 200 and listed.json()
