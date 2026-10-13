"""Authenticated server-to-server completion callbacks from n8n Cloud."""
import hashlib
import hmac
import json
from types import SimpleNamespace

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import Db
from app.config import get_settings
from app.intelligence.audit import record_audit
from app.intelligence.experiment_state import transition_dispatch, transition_experiment
from app.models import (Experiment, ExperimentApproval, ExperimentDesign, ExperimentEvaluation,
                        Membership, N8nCallbackReceipt, N8nDispatch, WorkflowJob)
from app.schemas import N8nSimulationCallback
from app.workflow_jobs import enqueue_job, job_view

router = APIRouter(prefix="/api/integrations/n8n")
def _payload_hash(payload: N8nSimulationCallback) -> tuple[str, dict]:
    data = payload.model_dump(mode="json")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), data


def _response(receipt, evaluation, evaluation_job, duplicate: bool):
    successful = receipt.event_type.endswith("completed")
    terminal_status = "completed" if successful else "execution_failed"
    return {"callback_id": receipt.callback_id, "experiment_id": receipt.experiment_id,
            "execution_id": receipt.payload["execution_id"], "experiment_status": terminal_status,
            "dispatch_status": terminal_status, "completion_status": "completed" if successful else "failed",
            "evaluation": ({"id": evaluation.id, "classification": evaluation.outcome,
                            "report": evaluation.report} if evaluation else None),
            "evaluation_job": job_view(evaluation_job) if evaluation_job else None,
            "duplicate": duplicate,
            "message": "Simulation callback recorded; evaluation is queued and does not establish a real business outcome."}


def _saved_response(db, receipt, duplicate: bool):
    evaluation = db.scalar(select(ExperimentEvaluation).where(
        ExperimentEvaluation.workspace_id == receipt.workspace_id,
        ExperimentEvaluation.experiment_id == receipt.experiment_id,
    ))
    evaluation_job = db.scalar(select(WorkflowJob).where(
        WorkflowJob.workspace_id == receipt.workspace_id, WorkflowJob.kind == "experiment_evaluation",
        WorkflowJob.payload["callback_receipt_id"].as_string() == receipt.id,
    ))
    if duplicate:
        record_audit(db, SimpleNamespace(workspace_id=receipt.workspace_id), None,
                     "experiment.callback_replayed", "experiment", receipt.experiment_id,
                     {"callback_id": receipt.callback_id, "execution_id": receipt.payload["execution_id"]})
        db.commit()
    return _response(receipt, evaluation, evaluation_job, duplicate)


@router.post("/simulation-callback")
def simulation_callback(payload: N8nSimulationCallback, db: Db,
                        authorization: str | None = Header(default=None)):
    settings = get_settings()
    secret = settings.n8n_callback_token.get_secret_value() if settings.n8n_callback_token else ""
    if not secret:
        raise HTTPException(503, "n8n callback authentication is not configured")
    expected = f"Bearer {secret}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Callback authentication failed")

    payload_hash, payload_data = _payload_hash(payload)
    # The callback's claims are checked against all persisted relationships; IDs
    # in the body alone never establish workspace membership or experiment state.
    rows = db.execute(select(N8nDispatch, Experiment, ExperimentApproval).join(
        Experiment, (Experiment.id == N8nDispatch.experiment_id)
        & (Experiment.workspace_id == N8nDispatch.workspace_id),
    ).join(ExperimentApproval, (ExperimentApproval.id == N8nDispatch.approval_id)
           & (ExperimentApproval.experiment_id == Experiment.id)
           & (ExperimentApproval.workspace_id == Experiment.workspace_id)).join(
        Membership, (Membership.workspace_id == ExperimentApproval.workspace_id)
        & (Membership.user_id == ExperimentApproval.approved_by_user_id),
    ).where(N8nDispatch.execution_id == payload.execution_id,
            N8nDispatch.workspace_id == payload.workspace_id,
            Experiment.id == payload.experiment_id,
            Experiment.version == payload.experiment_version,
            Experiment.action_type == "simulation_only",
            ExperimentApproval.id == payload.approval_id,
            ExperimentApproval.experiment_version == payload.experiment_version,
            ExperimentApproval.status == "approved",
            Experiment.created_by_user_id == ExperimentApproval.approved_by_user_id,
            Membership.role == "owner").with_for_update(of=N8nDispatch)).first()
    if rows is None:
        raise HTTPException(404, "Matching approved simulation execution not found")
    dispatch, experiment, approval = rows

    prior_callback = db.scalar(select(N8nCallbackReceipt).where(
        N8nCallbackReceipt.callback_id == payload.callback_id,
    ))
    if prior_callback:
        if (prior_callback.workspace_id != payload.workspace_id or prior_callback.dispatch_id != dispatch.id
                or prior_callback.payload_hash != payload_hash):
            raise HTTPException(409, "Callback ID was already used for a different event")
        return _saved_response(db, prior_callback, duplicate=True)

    prior_completion = db.scalar(select(N8nCallbackReceipt).where(
        N8nCallbackReceipt.workspace_id == payload.workspace_id,
        N8nCallbackReceipt.dispatch_id == dispatch.id,
    ))
    if prior_completion:
        record_audit(db, SimpleNamespace(workspace_id=payload.workspace_id), None,
                     "experiment.callback_duplicate_completion", "experiment", experiment.id,
                     {"callback_id": payload.callback_id, "execution_id": dispatch.execution_id})
        db.commit()
        raise HTTPException(409, "A completion callback is already recorded for this execution")
    if experiment.status != "approved" or dispatch.status not in {"dispatching", "acknowledged", "failed"}:
        raise HTTPException(409, "Experiment is not awaiting a simulation completion callback")

    design_row = db.scalar(select(ExperimentDesign).where(
        ExperimentDesign.workspace_id == payload.workspace_id,
        ExperimentDesign.experiment_id == experiment.id,
        ExperimentDesign.experiment_version == payload.experiment_version,
    ))
    result = payload.result.model_dump(mode="json") if payload.result else None
    if result is not None:
        expected_metrics = {"estimated_profit"}
        if design_row:
            expected_metrics.add(design_row.design["success_metrics"][0]["metric"])
        if set(result["metrics"]) - expected_metrics:
            raise HTTPException(422, "Simulation callback contains unsupported metric names")

    receipt = N8nCallbackReceipt(callback_id=payload.callback_id,
                                 workspace_id=payload.workspace_id, experiment_id=experiment.id,
                                 dispatch_id=dispatch.id, event_type=payload.event,
                                 payload_hash=payload_hash, payload=payload_data)
    db.add(receipt)
    try:
        db.flush()
        callback_status = "completed" if payload.event.endswith("completed") else "failed"
        terminal_status = "completed" if callback_status == "completed" else "execution_failed"
        transition_experiment(experiment, terminal_status)
        transition_dispatch(dispatch, terminal_status)
        if callback_status == "failed":
            dispatch.failure_code = payload.failure_code
        evaluation_job, _ = enqueue_job(
            db, workspace_id=payload.workspace_id, requested_by_user_id=None,
            kind="experiment_evaluation", payload={"callback_receipt_id": receipt.id},
            idempotency_key=f"system:evaluation:{dispatch.id}",
        )
        record_audit(db, SimpleNamespace(workspace_id=payload.workspace_id), None,
                     "experiment.simulation_callback_recorded", "experiment", experiment.id,
                     {"execution_id": dispatch.execution_id, "callback_id": receipt.callback_id,
                      "evaluation_job_id": evaluation_job.id, "mode": "simulation_only"})
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(N8nCallbackReceipt).where(
            N8nCallbackReceipt.workspace_id == payload.workspace_id,
            N8nCallbackReceipt.dispatch_id == dispatch.id,
        ))
        if prior and prior.payload_hash == payload_hash:
            return _saved_response(db, prior, duplicate=True)
        raise HTTPException(409, "Callback was already recorded; no second completion was applied") from None
    return _response(receipt, None, evaluation_job, duplicate=False)
