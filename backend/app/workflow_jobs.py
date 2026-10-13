"""Database-backed queue and checkpointed LangGraph worker for tenant workflows."""
import threading
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import SessionLocal, set_db_scope
from app.intelligence.checkpoint_store import TenantCheckpointSaver
from app.models import WorkflowJob
from app.job_lease import LeaseLost, fence_session, lease_heartbeat

logger = logging.getLogger("marketmind.worker")

LEASE_SECONDS = 300
POLL_SECONDS = 0.5
MAX_ATTEMPTS = 2


class JobState(TypedDict, total=False):
    job_id: str
    workspace_id: str
    requested_by_user_id: str | None
    kind: str
    payload: dict[str, Any]
    lease_token: str
    output: dict[str, Any]


class WorkflowJobError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def job_view(row: WorkflowJob) -> dict:
    return {"id": row.id, "kind": row.kind, "status": row.status, "attempts": row.attempts,
            "current_step": row.current_step, "cancel_requested": row.cancel_requested,
            "result": row.result, "error_code": row.error_code, "created_at": row.created_at,
            "updated_at": row.updated_at, "started_at": row.started_at, "finished_at": row.finished_at}


def enqueue_job(session, *, workspace_id: str, requested_by_user_id: str | None, kind: str,
                payload: dict, idempotency_key: str) -> tuple[WorkflowJob, bool]:
    existing = session.scalar(select(WorkflowJob).where(
        WorkflowJob.workspace_id == workspace_id, WorkflowJob.kind == kind,
        WorkflowJob.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        if existing.payload != payload:
            raise WorkflowJobError("idempotency_key_reused")
        return existing, True
    row = WorkflowJob(workspace_id=workspace_id, requested_by_user_id=requested_by_user_id,
                      kind=kind, status="queued", idempotency_key=idempotency_key,
                      payload=payload, created_at=_now(), updated_at=_now())
    session.add(row)
    session.flush()
    return row, False


def _session_factory() -> sessionmaker:
    try:
        from app.main import app
        return getattr(app.state, "workflow_session_factory",
                       getattr(app.state, "test_session_factory", SessionLocal))
    except (ImportError, AttributeError):
        return SessionLocal


def _load_owner(session, workspace_id: str, user_id: str | None):
    from app.models import Membership, User, Workspace
    if not user_id:
        raise WorkflowJobError("requester_access_revoked")
    workspace = session.scalar(select(Workspace).join(Membership).where(
        Workspace.id == workspace_id, Membership.workspace_id == workspace_id,
        Membership.user_id == user_id,
    ))
    user = session.get(User, user_id)
    if workspace is None or user is None:
        raise WorkflowJobError("requester_access_revoked")
    return user, workspace


def _assert_not_cancelled(session, job_id: str, workspace_id: str) -> WorkflowJob:
    job = session.scalar(select(WorkflowJob).where(
        WorkflowJob.id == job_id, WorkflowJob.workspace_id == workspace_id,
    ))
    if job is None:
        raise WorkflowJobError("job_unavailable")
    if job.cancel_requested:
        raise WorkflowJobError("cancelled")
    return job


def _report_for_investigation(run) -> dict:
    return {"id": run.id, "question": run.question, "status": run.status,
            "created_at": run.created_at.isoformat(), "result": run.result,
            "confidence": float(run.confidence) if run.confidence is not None else None,
            "model": run.model, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
            "estimated_cost_usd": float(run.estimated_cost_usd) if run.estimated_cost_usd is not None else None,
            "cost_schedule": run.cost_schedule, "prompt_version": run.prompt_version}


def _execute_investigation(session, job: WorkflowJob) -> dict:
    from app.api import digest_text, investigation_agent, require_context
    from app.intelligence.audit import record_audit
    from app.intelligence.investigation import InvestigationError
    from app.models import InvestigationRun

    user, workspace = _load_owner(session, job.workspace_id, job.requested_by_user_id)
    context = require_context(session, user, workspace)
    question = job.payload["question"]
    prior = session.scalar(select(InvestigationRun).where(
        InvestigationRun.workspace_id == job.workspace_id,
        InvestigationRun.job_id == job.id,
    )) if hasattr(InvestigationRun, "job_id") else None
    if prior is not None:
        result = {"resource_id": prior.id, "report": _report_for_investigation(prior)}
        job.result = result
        session.commit()
        return result
    try:
        analysis = investigation_agent.investigate(session, context, question)
    except InvestigationError:
        raise WorkflowJobError("investigation_provider_or_validation_failed") from None
    _assert_not_cancelled(session, job.id, job.workspace_id)
    # Authorization is checked again after provider latency before private output is saved.
    user, workspace = _load_owner(session, job.workspace_id, job.requested_by_user_id)
    context = require_context(session, user, workspace)
    run = InvestigationRun(workspace_id=job.workspace_id, job_id=job.id, question=question,
                           status=analysis["status"], result=analysis["result"], model=analysis["model"],
                           prompt_version=analysis["prompt_version"], input_tokens=analysis["input_tokens"],
                           output_tokens=analysis["output_tokens"], confidence=analysis["confidence"],
                           estimated_cost_usd=analysis["estimated_cost_usd"], cost_schedule=analysis["cost_schedule"])
    session.add(run)
    session.flush()
    report = _report_for_investigation(run)
    output = {"resource_id": run.id, "report": report}
    record_audit(session, context, user.id,
                 "investigation.analyzed" if analysis["model"] else "investigation.evidence_reviewed",
                 "investigation", run.id,
                 {"job_id": job.id, "question_digest": digest_text(question), "status": analysis["status"],
                  "model": analysis["model"], "prompt_version": analysis["prompt_version"],
                  "input_tokens": analysis["input_tokens"], "output_tokens": analysis["output_tokens"],
                  "estimated_cost_usd": str(analysis["estimated_cost_usd"])
                  if analysis["estimated_cost_usd"] is not None else None,
                  "cost_schedule": analysis["cost_schedule"]})
    job.result = output
    session.commit()
    return output


def _growth_result(session, workspace_id: str, strategy_run) -> dict:
    from fastapi.encoders import jsonable_encoder
    from app.growth_api import recommendation_view
    from app.models import GrowthRecommendation
    rows = session.scalars(select(GrowthRecommendation).where(
        GrowthRecommendation.workspace_id == workspace_id,
        GrowthRecommendation.strategy_run_id == strategy_run.id,
    )).all()
    recommendations = sorted((recommendation_view(row, strategy_run) for row in rows),
                             key=lambda row: row["content"]["priority"])
    return jsonable_encoder({"resource_id": strategy_run.id, "strategy_run_id": strategy_run.id,
                             "source_type": strategy_run.source_type,
                             "recommendations": recommendations,
                             "message": "No supported, evidence-backed action within these constraints was found." if not rows else
                                        "Review each hypothesis, cost estimate and constraint before approving a recommendation."})


def _execute_growth_strategy(session, job: WorkflowJob) -> dict:
    from app.api import require_context
    from app.config import get_settings
    from app.growth_api import assert_fresh_evidence, investigation_for, strategy_agent
    from app.intelligence.audit import record_audit
    from app.intelligence.growth import PROMPT_VERSION
    from app.intelligence.reporting import business_snapshot, fingerprint
    from app.models import GrowthRecommendation, GrowthStrategyRun

    user, workspace = _load_owner(session, job.workspace_id, job.requested_by_user_id)
    context = require_context(session, user, workspace)
    run_id = job.payload["investigation_id"]
    investigation = investigation_for(session, context, run_id)
    assert_fresh_evidence(session, workspace, context, investigation)
    snapshot = business_snapshot(context, workspace.currency)
    settings = get_settings()
    key = fingerprint({"context": snapshot, "provider": settings.strategy_provider,
                       "model": settings.investigation_model, "prompt_version": PROMPT_VERSION})
    existing = session.scalar(select(GrowthStrategyRun).where(
        GrowthStrategyRun.workspace_id == job.workspace_id,
        GrowthStrategyRun.investigation_id == run_id, GrowthStrategyRun.generation_key == key,
    ))
    if existing is not None:
        output = _growth_result(session, job.workspace_id, existing)
        job.result = output
        session.commit()
        return output

    try:
        from app.api import investigation_agent
        investigation_agent.require_workspace_run(context, investigation)
        generated = strategy_agent.recommend(context, investigation)
    except Exception as error:
        from app.intelligence.growth import StrategyError
        from app.intelligence.investigation import InvestigationError
        if isinstance(error, InvestigationError):
            raise WorkflowJobError("growth_investigation_failed") from None
        if isinstance(error, (StrategyError, PermissionError)):
            raise WorkflowJobError("growth_validation_failed") from None
        raise
    _assert_not_cancelled(session, job.id, job.workspace_id)
    user, workspace = _load_owner(session, job.workspace_id, job.requested_by_user_id)
    context = require_context(session, user, workspace)
    current_investigation = investigation_for(session, context, run_id)
    assert_fresh_evidence(session, workspace, context, current_investigation)
    if fingerprint(business_snapshot(context, workspace.currency)) != fingerprint(snapshot):
        raise WorkflowJobError("business_context_changed")
    strategy_run = GrowthStrategyRun(workspace_id=workspace.id, investigation_id=run_id, generation_key=key,
                                     context_snapshot=snapshot, source_type=generated["source_type"],
                                     model=generated["model"], prompt_version=PROMPT_VERSION,
                                     input_tokens=generated.get("input_tokens"),
                                     output_tokens=generated.get("output_tokens"),
                                     estimated_cost_usd=generated.get("estimated_cost_usd"),
                                     cost_schedule=generated.get("cost_schedule"))
    session.add(strategy_run)
    session.flush()
    for recommendation in generated["recommendations"]:
        session.add(GrowthRecommendation(workspace_id=workspace.id, strategy_run_id=strategy_run.id,
                                         candidate_key=recommendation["key"], content=recommendation))
    record_audit(session, context, user.id, "growth.strategy_generated", "growth_strategy", strategy_run.id,
                 {"job_id": job.id, "investigation_id": run_id, "count": len(generated["recommendations"]),
                  "source_type": generated["source_type"], "model": generated["model"]})
    output = _growth_result(session, workspace.id, strategy_run)
    job.result = output
    session.commit()
    return output


def _execute_experiment_evaluation(session, job: WorkflowJob) -> dict:
    from types import SimpleNamespace

    from app.intelligence.audit import record_audit
    from app.intelligence.evaluation import EvaluationAgent, LearningMemoryAgent
    from app.models import (Experiment, ExperimentApproval, ExperimentDesign, ExperimentEvaluation,
                            ExperimentLearning, Membership, N8nCallbackReceipt, N8nDispatch)

    receipt = session.scalar(select(N8nCallbackReceipt).where(
        N8nCallbackReceipt.id == job.payload["callback_receipt_id"],
        N8nCallbackReceipt.workspace_id == job.workspace_id,
    ))
    if receipt is None:
        raise WorkflowJobError("evaluation_receipt_unavailable")
    existing = session.scalar(select(ExperimentEvaluation).where(
        ExperimentEvaluation.workspace_id == job.workspace_id,
        ExperimentEvaluation.experiment_id == receipt.experiment_id,
    ))
    if existing is not None:
        learning = session.scalar(select(ExperimentLearning).where(
            ExperimentLearning.workspace_id == job.workspace_id,
            ExperimentLearning.experiment_id == receipt.experiment_id,
        ))
        output = {"resource_id": existing.id, "evaluation_id": existing.id,
                  "classification": existing.outcome, "learning_id": learning.id if learning else None}
        job.result = output
        session.commit()
        return output

    rows = session.execute(select(N8nDispatch, Experiment, ExperimentApproval).join(
        Experiment, (Experiment.id == N8nDispatch.experiment_id)
        & (Experiment.workspace_id == N8nDispatch.workspace_id),
    ).join(ExperimentApproval, (ExperimentApproval.id == N8nDispatch.approval_id)
           & (ExperimentApproval.experiment_id == Experiment.id)
           & (ExperimentApproval.workspace_id == Experiment.workspace_id),
    ).join(Membership, (Membership.workspace_id == ExperimentApproval.workspace_id)
           & (Membership.user_id == ExperimentApproval.approved_by_user_id),
    ).where(N8nDispatch.id == receipt.dispatch_id, N8nDispatch.workspace_id == job.workspace_id,
            Experiment.id == receipt.experiment_id, Experiment.action_type == "simulation_only",
            Experiment.status.in_(["completed", "execution_failed"]),
            ExperimentApproval.status == "approved", Experiment.version == ExperimentApproval.experiment_version,
            Experiment.created_by_user_id == ExperimentApproval.approved_by_user_id,
            Membership.role == "owner")).first()
    if rows is None:
        raise WorkflowJobError("evaluation_approval_or_tenant_revalidation_failed")
    dispatch, experiment, approval = rows
    design_row = session.scalar(select(ExperimentDesign).where(
        ExperimentDesign.workspace_id == job.workspace_id,
        ExperimentDesign.experiment_id == experiment.id,
        ExperimentDesign.experiment_version == approval.experiment_version,
    ))
    callback_status = "completed" if receipt.event_type.endswith("completed") else "failed"
    callback_result = receipt.payload.get("result")
    evaluation = EvaluationAgent().evaluate(design_row.design if design_row else None,
                                            callback_status, callback_result)
    saved = ExperimentEvaluation(workspace_id=job.workspace_id, experiment_id=experiment.id,
                                 callback_receipt_id=receipt.id,
                                 outcome=evaluation["classification"], report=evaluation)
    session.add(saved)
    session.flush()
    learning = LearningMemoryAgent().create_learning(
        experiment, design_row.design if design_row else None, callback_status, callback_result,
        evaluation, design_row.recommendation_id if design_row else None,
        design_row.recommendation_approval_id if design_row else None, approval.id,
    )
    saved_learning = ExperimentLearning(workspace_id=job.workspace_id, experiment_id=experiment.id,
                                        evaluation_id=saved.id, content=learning)
    session.add(saved_learning)
    record_audit(session, SimpleNamespace(workspace_id=job.workspace_id), None,
                 "experiment.simulation_evaluated", "experiment", experiment.id,
                 {"job_id": job.id, "execution_id": dispatch.execution_id,
                  "evaluation": evaluation["classification"], "mode": "simulation_only"})
    output = {"resource_id": saved.id, "evaluation_id": saved.id,
              "classification": saved.outcome, "learning_id": saved_learning.id}
    job.result = output
    session.commit()
    return output


def _execute_job(session_factory: sessionmaker, state: JobState) -> dict:
    with session_factory() as session:
        fence_session(session, state["workspace_id"], state["job_id"], state.get("lease_token"))
        job = session.scalar(select(WorkflowJob).where(
            WorkflowJob.id == state["job_id"], WorkflowJob.workspace_id == state["workspace_id"],
        ))
        if job is None:
            raise WorkflowJobError("job_unavailable")
        if job.result is not None:
            return job.result
        _assert_not_cancelled(session, job.id, job.workspace_id)
        job.current_step = job.kind
        job.updated_at = _now()
        session.commit()
        if job.kind == "investigation":
            return _execute_investigation(session, job)
        if job.kind == "growth_strategy":
            return _execute_growth_strategy(session, job)
        if job.kind == "experiment_evaluation":
            return _execute_experiment_evaluation(session, job)
        raise WorkflowJobError("unknown_job_kind")


def _compiled_job_graph(session_factory: sessionmaker):
    graph = StateGraph(JobState)
    graph.add_node("execute_workflow", lambda state: {"output": _execute_job(session_factory, state)})
    graph.add_edge(START, "execute_workflow")
    graph.add_edge("execute_workflow", END)
    return graph.compile(checkpointer=TenantCheckpointSaver(session_factory))


def _claim_job(session_factory: sessionmaker, job_id: str | None = None) -> WorkflowJob | None:
    now = _now()
    with session_factory.begin() as session:
        query = select(WorkflowJob).where(WorkflowJob.status == "queued",
                                          WorkflowJob.cancel_requested.is_(False)).order_by(
            WorkflowJob.created_at, WorkflowJob.id,
        ).with_for_update(skip_locked=True)
        if job_id:
            query = query.where(WorkflowJob.id == job_id)
        job = session.scalar(query.limit(1))
        if job is None:
            return None
        token = str(uuid.uuid4())
        claimed = session.execute(update(WorkflowJob).where(
            WorkflowJob.id == job.id, WorkflowJob.workspace_id == job.workspace_id,
            WorkflowJob.status == "queued", WorkflowJob.cancel_requested.is_(False),
        ).values(status="running", attempts=WorkflowJob.attempts + 1,
                 lease_token=token, lease_expires_at=now + timedelta(seconds=get_settings().worker_lease_seconds),
                 current_step="claimed", started_at=now, updated_at=now))
        if claimed.rowcount != 1:
            return None
        session.flush()
        session.refresh(job)
        return job


def _recover_expired(session_factory: sessionmaker) -> None:
    now = _now()
    with session_factory.begin() as session:
        expired = session.scalars(select(WorkflowJob).where(
            WorkflowJob.status == "running", WorkflowJob.lease_expires_at < now,
        ).with_for_update(skip_locked=True).limit(100)).all()
        for job in expired:
            if job.result is not None:
                job.status = "completed"
                job.finished_at = now
                job.current_step = None
                job.lease_token = None
                job.lease_expires_at = None
                continue
            if job.current_step == "claimed" and job.attempts < MAX_ATTEMPTS:
                job.status = "queued"
                job.current_step = None
                job.lease_token = None
                job.lease_expires_at = None
                continue
            # A checkpoint without a committed domain result cannot prove that
            # the provider node finished. Never replay uncertain paid calls.
            job.status = "failed"
            job.error_code = "worker_interrupted_during_step"
            job.finished_at = now
            job.current_step = None
            job.lease_token = None
            job.lease_expires_at = None


def process_next_job(session_factory: sessionmaker | None = None, job_id: str | None = None) -> dict | None:
    session_factory = session_factory or _session_factory()
    _recover_expired(session_factory)
    job = _claim_job(session_factory, job_id)
    if job is None:
        return None
    with session_factory.begin() as session:
        set_db_scope(session, workspace_id=job.workspace_id)
        current = session.scalar(select(WorkflowJob).where(
            WorkflowJob.id == job.id, WorkflowJob.workspace_id == job.workspace_id,
            WorkflowJob.status == "running", WorkflowJob.lease_token == job.lease_token,
        ))
        if current is None:
            return None
        if current.cancel_requested:
            current.status = "cancelled"
            current.finished_at = _now()
            current.lease_token = None
            current.lease_expires_at = None
            return job_view(current)
        current.current_step = "workflow"
        current.updated_at = _now()
    config = {"configurable": {"thread_id": job.id, "workspace_id": job.workspace_id,
                                "checkpoint_ns": "", "lease_token": job.lease_token}}
    initial: JobState = {"job_id": job.id, "workspace_id": job.workspace_id,
                         "requested_by_user_id": job.requested_by_user_id,
                         "kind": job.kind, "payload": job.payload, "lease_token": job.lease_token}
    try:
        logger.info("job_started workspace_id=%s job_id=%s kind=%s", job.workspace_id, job.id, job.kind)
        with lease_heartbeat(session_factory, job.workspace_id, job.id, job.lease_token):
            output_state = _compiled_job_graph(session_factory).invoke(initial, config=config)
        with session_factory.begin() as session:
            set_db_scope(session, workspace_id=job.workspace_id)
            completed = session.scalar(select(WorkflowJob).where(
                WorkflowJob.id == job.id, WorkflowJob.workspace_id == job.workspace_id,
                WorkflowJob.status == "running", WorkflowJob.lease_token == job.lease_token,
            ))
            if completed is not None:
                completed.result = completed.result or output_state.get("output")
                completed.status = "completed"
                completed.error_code = None
                completed.current_step = None
                completed.finished_at = _now()
                completed.updated_at = _now()
                completed.lease_token = None
                completed.lease_expires_at = None
                return job_view(completed)
    except (WorkflowJobError, LeaseLost) as error:
        with session_factory.begin() as session:
            set_db_scope(session, workspace_id=job.workspace_id)
            failed = session.scalar(select(WorkflowJob).where(
                WorkflowJob.id == job.id, WorkflowJob.workspace_id == job.workspace_id,
                WorkflowJob.status == "running", WorkflowJob.lease_token == job.lease_token,
            ))
            if failed is not None:
                code = error.code if isinstance(error, WorkflowJobError) else "worker_lease_lost"
                if failed.result is not None:
                    failed.status = "completed"
                    failed.error_code = None
                else:
                    failed.status = "cancelled" if code == "cancelled" or failed.cancel_requested else "failed"
                    failed.error_code = None if failed.status == "cancelled" else code
                failed.current_step = None
                failed.finished_at = _now()
                failed.updated_at = _now()
                failed.lease_token = None
                failed.lease_expires_at = None
                return job_view(failed)
    except Exception as error:
        logger.error("job_step_failed job_id=%s error_type=%s", job.id, type(error).__name__)
        with session_factory.begin() as session:
            set_db_scope(session, workspace_id=job.workspace_id)
            failed = session.scalar(select(WorkflowJob).where(
                WorkflowJob.id == job.id, WorkflowJob.workspace_id == job.workspace_id,
                WorkflowJob.status == "running", WorkflowJob.lease_token == job.lease_token,
            ))
            if failed is not None:
                if failed.result is not None:
                    failed.status = "completed"
                    failed.error_code = None
                else:
                    failed.status = "failed"
                    failed.error_code = "workflow_step_failed"
                failed.current_step = None
                failed.finished_at = _now()
                failed.updated_at = _now()
                failed.lease_token = None
                failed.lease_expires_at = None
                return job_view(failed)
    return None


def _worker_loop(stop: threading.Event, factory: sessionmaker | None = None) -> None:
    factory = factory or _session_factory()
    while not stop.is_set():
        try:
            result = process_next_job(factory)
            if result is None:
                stop.wait(get_settings().worker_poll_seconds)
            else:
                logger.info("job_finished job_id=%s status=%s error_code=%s",
                            result["id"], result["status"], result["error_code"])
        except Exception as error:
            # A transient polling/session error must not terminate the worker.
            logger.warning("worker_poll_failed error_type=%s", type(error).__name__)
            stop.wait(5)


def start_worker(app) -> Callable[[], None]:
    if not get_settings().workflow_worker_enabled or getattr(app.state, "disable_workflow_worker", False):
        return lambda: None
    existing = getattr(app.state, "workflow_worker_stop", None)
    if existing:
        return lambda: None
    stop = threading.Event()
    thread = threading.Thread(target=_worker_loop, args=(stop,), name="marketmind-workflow-worker", daemon=True)
    app.state.workflow_worker_stop = stop
    app.state.workflow_worker_thread = thread
    thread.start()

    def shutdown():
        stop.set()
        thread.join(timeout=5)
        app.state.workflow_worker_stop = None
        app.state.workflow_worker_thread = None
    return shutdown
