"""Tenant-scoped strategy and design routes; approvals are separate from execution."""
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.analytics import dashboard
from app.api import investigation_agent, require_context, require_workspace_owner
from app.auth import CurrentUser, Db, Tenant
from app.config import get_settings
from app.intelligence.audit import record_audit
from app.intelligence.experimentation import ExperimentDesignAgent
from app.intelligence.growth import PROMPT_VERSION, GrowthStrategyAgent, StrategyError, blocked_action
from app.intelligence.investigation import InvestigationError
from app.intelligence.reporting import business_snapshot, fingerprint, metric_fingerprint
from app.intelligence.workflow import build_growth_experiment_graph
from app.models import (AuditEvent, Experiment, ExperimentApproval, ExperimentDesign, ExperimentEvaluation,
                        ExperimentLearning, GrowthRecommendation, GrowthStrategyRun, InvestigationRun,
                        KnowledgeChunk, Membership, N8nCallbackReceipt, N8nDispatch, RecommendationApproval, WorkflowJob)
from app.schemas import ExperimentDesignRequest, RecommendationDecision

router = APIRouter(prefix="/api")
strategy_agent = GrowthStrategyAgent()
design_agent = ExperimentDesignAgent()
growth_workflow = build_growth_experiment_graph(investigation_agent, strategy_agent, design_agent)


def investigation_for(db, context, run_id):
    run = db.scalar(select(InvestigationRun).where(
        InvestigationRun.id == run_id, InvestigationRun.workspace_id == context.workspace_id,
    ))
    if run is None:
        raise HTTPException(404, "Investigation not found")
    return run


def assert_fresh_evidence(db, workspace, context, investigation):
    result = investigation.result
    if "metric_snapshot_digest" not in result or "reporting_period" not in result:
        raise HTTPException(409, "Create a new investigation to capture its financial reporting snapshot")
    period = result["reporting_period"]
    current = dashboard(db, workspace, context.industry_pack,
                        date.fromisoformat(period["start"]) if period["start"] else None,
                        date.fromisoformat(period["end"]) if period["end"] else None)
    if metric_fingerprint(current) != result["metric_snapshot_digest"]:
        raise HTTPException(409, "Investigation financial evidence changed; create a new investigation")
    ids = {source["id"] for source in result.get("evidence_sources", [])}
    if ids:
        existing = set(db.scalars(select(KnowledgeChunk.id).where(
            KnowledgeChunk.workspace_id == context.workspace_id, KnowledgeChunk.id.in_(ids),
        )))
        if existing != ids:
            raise HTTPException(409, "Investigation source documents are unavailable; create a new investigation")


def recommendation_for(db, context, recommendation_id, lock=False):
    query = select(GrowthRecommendation).where(
        GrowthRecommendation.id == recommendation_id, GrowthRecommendation.workspace_id == context.workspace_id,
    )
    recommendation = db.scalar(query.with_for_update() if lock else query)
    if recommendation is None:
        raise HTTPException(404, "Recommendation not found")
    strategy = db.scalar(select(GrowthStrategyRun).where(
        GrowthStrategyRun.id == recommendation.strategy_run_id, GrowthStrategyRun.workspace_id == context.workspace_id,
    ))
    if strategy is None:
        raise HTTPException(409, "Recommendation provenance is unavailable")
    return recommendation, strategy


def assert_current_recommendation(db, workspace, context, recommendation, strategy):
    if fingerprint(business_snapshot(context, workspace.currency)) != fingerprint(strategy.context_snapshot):
        raise HTTPException(409, "Business goals, budget, constraints or industry configuration changed; regenerate recommendations")
    investigation = investigation_for(db, context, strategy.investigation_id)
    assert_fresh_evidence(db, workspace, context, investigation)
    if blocked_action(context, recommendation.content["action_type"]):
        raise HTTPException(409, "Business constraints block this action")
    return investigation


def recommendation_view(row, strategy):
    return {"id": row.id, "version": row.version, "status": row.status, "created_at": row.created_at,
            "investigation_id": strategy.investigation_id, "source_type": strategy.source_type,
            "model": strategy.model, "prompt_version": strategy.prompt_version, "content": row.content,
            "model_usage": {"input_tokens": strategy.input_tokens, "output_tokens": strategy.output_tokens,
                            "estimated_cost_usd": strategy.estimated_cost_usd, "cost_schedule": strategy.cost_schedule}}


def design_view(row):
    return {"id": row.id, "experiment_id": row.experiment_id, "recommendation_id": row.recommendation_id,
            "recommendation_approval_id": row.recommendation_approval_id,
            "experiment_version": row.experiment_version, "created_at": row.created_at, "design": row.design}


@router.post("/investigations/{run_id}/recommendations")
def generate_recommendations(run_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    context = require_context(db, user, workspace)
    investigation = investigation_for(db, context, run_id)
    assert_fresh_evidence(db, workspace, context, investigation)
    snapshot = business_snapshot(context, workspace.currency)
    settings = get_settings()
    key = fingerprint({"context": snapshot, "provider": settings.strategy_provider,
                       "model": settings.investigation_model, "prompt_version": PROMPT_VERSION})
    existing = db.scalar(select(GrowthStrategyRun).where(
        GrowthStrategyRun.workspace_id == workspace.id, GrowthStrategyRun.investigation_id == run_id,
        GrowthStrategyRun.generation_key == key,
    ))
    if existing is None:
        try:
            output = growth_workflow.invoke({"context": context, "investigation": investigation})["strategy_output"]
        except (InvestigationError, StrategyError, PermissionError) as error:
            record_audit(db, context, user.id, "growth.strategy_failed", "investigation", run_id,
                         {"failure": "provider_or_evidence_validation"})
            db.commit()
            raise HTTPException(503 if isinstance(error, InvestigationError) else 409, str(error)) from None
        # Check again after provider latency; do not save proposals based on changed evidence.
        db.refresh(workspace)
        context = require_context(db, user, workspace)
        if fingerprint(business_snapshot(context, workspace.currency)) != fingerprint(snapshot):
            raise HTTPException(409, "Business context changed during strategy generation; retry")
        assert_fresh_evidence(db, workspace, context, investigation)
        existing = GrowthStrategyRun(workspace_id=workspace.id, investigation_id=run_id, generation_key=key,
                                     context_snapshot=snapshot, source_type=output["source_type"], model=output["model"],
                                     prompt_version=PROMPT_VERSION, input_tokens=output.get("input_tokens"),
                                     output_tokens=output.get("output_tokens"), estimated_cost_usd=output.get("estimated_cost_usd"),
                                     cost_schedule=output.get("cost_schedule"))
        db.add(existing)
        try:
            db.flush()
            for content in output["recommendations"]:
                db.add(GrowthRecommendation(workspace_id=workspace.id, strategy_run_id=existing.id,
                                           candidate_key=content["key"], content=content))
            record_audit(db, context, user.id, "growth.strategy_generated", "growth_strategy", existing.id,
                         {"investigation_id": run_id, "count": len(output["recommendations"]),
                          "source_type": output["source_type"], "model": output["model"]})
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Strategy generation already saved; retry to retrieve it") from None
    rows = db.scalars(select(GrowthRecommendation).where(
        GrowthRecommendation.workspace_id == workspace.id, GrowthRecommendation.strategy_run_id == existing.id,
    )).all()
    return {"strategy_run_id": existing.id, "source_type": existing.source_type,
            "recommendations": sorted((recommendation_view(row, existing) for row in rows),
                                      key=lambda row: row["content"]["priority"]),
            "message": "No supported, evidence-backed action within these constraints was found." if not rows else
                       "Review each hypothesis, cost estimate and constraint before approving a recommendation."}


@router.get("/growth/recommendations")
def list_recommendations(workspace: Tenant, db: Db, user: CurrentUser, investigation_id: str):
    context = require_context(db, user, workspace)
    investigation_for(db, context, investigation_id)
    rows = db.execute(select(GrowthRecommendation, GrowthStrategyRun).join(
        GrowthStrategyRun, GrowthRecommendation.strategy_run_id == GrowthStrategyRun.id,
    ).where(GrowthRecommendation.workspace_id == workspace.id, GrowthStrategyRun.workspace_id == workspace.id,
            GrowthStrategyRun.investigation_id == investigation_id)
      .order_by(GrowthStrategyRun.created_at.desc(), GrowthRecommendation.created_at).limit(100)).all()
    return [recommendation_view(row, strategy) for row, strategy in rows]


@router.post("/growth/recommendations/{recommendation_id}/approve")
def approve_recommendation(recommendation_id: str, payload: RecommendationDecision, workspace: Tenant, db: Db, user: CurrentUser):
    context = require_context(db, user, workspace)
    require_workspace_owner(db, user, workspace)
    row, strategy = recommendation_for(db, context, recommendation_id, lock=True)
    if row.version != payload.version or row.status not in {"proposed", "approved"}:
        raise HTTPException(409, "Recommendation version or state is not approvable")
    assert_current_recommendation(db, workspace, context, row, strategy)
    if context.constraints and not payload.constraints_acknowledged:
        raise HTTPException(422, "Review and acknowledge every configured constraint before approval")
    approval = db.scalar(select(RecommendationApproval).where(
        RecommendationApproval.workspace_id == workspace.id, RecommendationApproval.recommendation_id == row.id,
        RecommendationApproval.recommendation_version == row.version,
    ))
    if approval is None:
        approval = RecommendationApproval(workspace_id=workspace.id, recommendation_id=row.id,
                                          recommendation_version=row.version, approved_by_user_id=user.id,
                                          constraints_acknowledged=payload.constraints_acknowledged)
        row.status = "approved"
        db.add(approval)
        try:
            db.flush()
            record_audit(db, context, user.id, "growth.recommendation_approved", "growth_recommendation", row.id,
                         {"version": row.version, "approval_id": approval.id})
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Recommendation approval already saved; retry") from None
    return {**recommendation_view(row, strategy), "approval_id": approval.id}


@router.post("/growth/recommendations/{recommendation_id}/reject")
def reject_recommendation(recommendation_id: str, payload: RecommendationDecision, workspace: Tenant, db: Db, user: CurrentUser):
    context = require_context(db, user, workspace)
    require_workspace_owner(db, user, workspace)
    row, strategy = recommendation_for(db, context, recommendation_id, lock=True)
    if row.version != payload.version or row.status not in {"proposed", "rejected"}:
        raise HTTPException(409, "Only a proposed recommendation version can be rejected")
    if row.status != "rejected":
        row.status = "rejected"
        record_audit(db, context, user.id, "growth.recommendation_rejected", "growth_recommendation", row.id,
                     {"version": row.version})
        db.commit()
    return recommendation_view(row, strategy)


@router.post("/growth/recommendations/{recommendation_id}/experiment-design", status_code=201)
def create_design(recommendation_id: str, payload: ExperimentDesignRequest, workspace: Tenant, db: Db, user: CurrentUser):
    context = require_context(db, user, workspace)
    require_workspace_owner(db, user, workspace)
    row, strategy = recommendation_for(db, context, recommendation_id, lock=True)
    investigation = assert_current_recommendation(db, workspace, context, row, strategy)
    approval = db.scalar(select(RecommendationApproval).join(Membership, (
        Membership.user_id == RecommendationApproval.approved_by_user_id
    ) & (Membership.workspace_id == RecommendationApproval.workspace_id)).where(
        RecommendationApproval.workspace_id == workspace.id, RecommendationApproval.recommendation_id == row.id,
        RecommendationApproval.recommendation_version == row.version, Membership.role == "owner",
    ))
    if approval is None or row.status != "approved" or (context.constraints and not approval.constraints_acknowledged):
        raise HTTPException(409, "The exact recommendation version requires persisted owner approval")
    existing = db.scalar(select(ExperimentDesign).where(
        ExperimentDesign.workspace_id == workspace.id, ExperimentDesign.recommendation_id == row.id,
    ))
    if existing is not None:
        if existing.design["request"] != payload.model_dump(mode="json"):
            raise HTTPException(409, "An immutable experiment design already exists with different parameters")
        return design_view(existing)
    period = investigation.result["reporting_period"]
    if not period["start"] or not (date.fromisoformat(period["start"]) <= payload.baseline_start
                                  <= payload.baseline_end <= date.fromisoformat(period["end"])):
        raise HTTPException(422, "Baseline must be inside the investigation's imported reporting period")
    overview = dashboard(db, workspace, context.industry_pack, payload.baseline_start, payload.baseline_end)
    try:
        design = growth_workflow.invoke({"context": context, "investigation": investigation,
                                         "recommendation": row, "approval": approval,
                                         "approval_verified": True, "design_request": payload,
                                         "overview": overview})["experiment_design"]
    except (StrategyError, PermissionError) as error:
        raise HTTPException(422 if isinstance(error, StrategyError) else 409, str(error)) from None
    design["baseline"]["metric_snapshot_digest"] = metric_fingerprint(overview)
    experiment = Experiment(workspace_id=workspace.id, created_by_user_id=user.id, name=row.content["title"],
                            action_type="simulation_only", status="draft", version=1,
                            metadata_json={"scenario": "conversion_lift" if workspace.industry == "ecommerce" else "repeat_booking"})
    db.add(experiment)
    try:
        db.flush()
        saved = ExperimentDesign(workspace_id=workspace.id, experiment_id=experiment.id, recommendation_id=row.id,
                                 recommendation_approval_id=approval.id, experiment_version=experiment.version, design=design)
        db.add(saved)
        db.flush()
        record_audit(db, context, user.id, "experiment.designed", "experiment", experiment.id,
                     {"design_id": saved.id, "recommendation_id": row.id, "recommendation_version": row.version,
                      "approval_id": approval.id, "execution_mode": "simulation_only"})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Experiment design already saved; retry to retrieve it") from None
    return design_view(saved)


@router.get("/experiment-designs")
def list_designs(workspace: Tenant, db: Db, user: CurrentUser):
    require_context(db, user, workspace)
    rows = db.scalars(select(ExperimentDesign).where(ExperimentDesign.workspace_id == workspace.id)
                      .order_by(ExperimentDesign.created_at.desc()).limit(100)).all()
    return [design_view(row) for row in rows]


@router.get("/experiments")
def list_experiments(workspace: Tenant, db: Db, user: CurrentUser):
    """List only this member's workspace experiments with safe dispatch status."""
    require_context(db, user, workspace)
    membership = db.scalar(select(Membership).where(
        Membership.workspace_id == workspace.id, Membership.user_id == user.id,
    ))
    experiments = db.scalars(select(Experiment).where(
        Experiment.workspace_id == workspace.id,
    ).order_by(Experiment.created_at.desc()).limit(100)).all()
    rows = []
    for experiment in experiments:
        design = db.scalar(select(ExperimentDesign).where(
            ExperimentDesign.workspace_id == workspace.id, ExperimentDesign.experiment_id == experiment.id,
        ))
        approval = db.scalar(select(ExperimentApproval).where(
            ExperimentApproval.workspace_id == workspace.id, ExperimentApproval.experiment_id == experiment.id,
            ExperimentApproval.experiment_version == experiment.version, ExperimentApproval.status == "approved",
        ))
        dispatch = db.scalar(select(N8nDispatch).where(
            N8nDispatch.workspace_id == workspace.id, N8nDispatch.experiment_id == experiment.id,
        ).order_by(N8nDispatch.created_at.desc()))
        evaluation = db.scalar(select(ExperimentEvaluation).where(
            ExperimentEvaluation.workspace_id == workspace.id, ExperimentEvaluation.experiment_id == experiment.id,
        ))
        receipt = db.scalar(select(N8nCallbackReceipt).where(
            N8nCallbackReceipt.workspace_id == workspace.id, N8nCallbackReceipt.experiment_id == experiment.id,
        ))
        evaluation_job = db.scalar(select(WorkflowJob).where(
            WorkflowJob.workspace_id == workspace.id, WorkflowJob.kind == "experiment_evaluation",
            WorkflowJob.payload["callback_receipt_id"].as_string() == receipt.id,
        )) if receipt else None
        rows.append({"id": experiment.id, "name": experiment.name, "status": experiment.status,
                     "version": experiment.version, "action_type": experiment.action_type,
                     "created_at": experiment.created_at,
                     "can_approve": bool(membership and membership.role == "owner"
                                         and experiment.created_by_user_id == user.id),
                     "design": design_view(design) if design else None,
                     "approval_id": approval.id if approval else None,
                     "execution": ({"execution_id": dispatch.execution_id, "status": dispatch.status,
                                    "http_status": dispatch.http_status, "failure_code": dispatch.failure_code,
                                    "acknowledged_at": dispatch.acknowledged_at,
                                    "completion_status": ("completed" if dispatch.status == "completed" else
                                                          "failed" if dispatch.status == "execution_failed" else
                                                          "not_reported")} if dispatch else None),
                     "evaluation": ({"classification": evaluation.outcome,
                                     "simulation_only": evaluation.report["simulation_only"]} if evaluation else None),
                     "evaluation_job": ({"id": evaluation_job.id, "status": evaluation_job.status,
                                         "current_step": evaluation_job.current_step,
                                         "error_code": evaluation_job.error_code} if evaluation_job else None)})
    return rows


@router.get("/experiments/{experiment_id}/history")
def experiment_history(experiment_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    context = require_context(db, user, workspace)
    experiment = db.scalar(select(Experiment).where(
        Experiment.workspace_id == context.workspace_id, Experiment.id == experiment_id,
    ))
    if experiment is None:
        raise HTTPException(404, "Experiment not found")
    receipt = db.scalar(select(N8nCallbackReceipt).where(
        N8nCallbackReceipt.workspace_id == context.workspace_id,
        N8nCallbackReceipt.experiment_id == experiment.id,
    ))
    evaluation = db.scalar(select(ExperimentEvaluation).where(
        ExperimentEvaluation.workspace_id == context.workspace_id,
        ExperimentEvaluation.experiment_id == experiment.id,
    ))
    evaluation_job = None
    if receipt is not None:
        evaluation_job = db.scalar(select(WorkflowJob).where(
            WorkflowJob.workspace_id == context.workspace_id, WorkflowJob.kind == "experiment_evaluation",
            WorkflowJob.payload["callback_receipt_id"].as_string() == receipt.id,
        ))
    learning = db.scalar(select(ExperimentLearning).where(
        ExperimentLearning.workspace_id == context.workspace_id,
        ExperimentLearning.experiment_id == experiment.id,
    ))
    events = db.scalars(select(AuditEvent).where(
        AuditEvent.workspace_id == context.workspace_id, AuditEvent.resource_type == "experiment",
        AuditEvent.resource_id == experiment.id,
    ).order_by(AuditEvent.created_at, AuditEvent.id)).all()
    return {"experiment_id": experiment.id, "status": experiment.status,
            "callback": ({"event": receipt.event_type, "received_at": receipt.received_at,
                          "payload": receipt.payload} if receipt else None),
            "evaluation_job": ({"id": evaluation_job.id, "status": evaluation_job.status,
                                "current_step": evaluation_job.current_step,
                                "error_code": evaluation_job.error_code} if evaluation_job else None),
            "evaluation": ({"id": evaluation.id, "classification": evaluation.outcome,
                            "report": evaluation.report} if evaluation else None),
            "learning": ({"id": learning.id, "content": learning.content} if learning else None),
            "history": [{"action": event.action, "created_at": event.created_at,
                         "details": event.details} for event in events]}


@router.get("/experiment-designs/{design_id}")
def get_design(design_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    require_context(db, user, workspace)
    row = db.scalar(select(ExperimentDesign).where(ExperimentDesign.workspace_id == workspace.id,
                                                  ExperimentDesign.id == design_id))
    if row is None:
        raise HTTPException(404, "Experiment design not found")
    return design_view(row)
