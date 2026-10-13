"""Final freshness and tenant checks for designed simulation dispatches."""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.analytics import dashboard
from app.intelligence.growth import blocked_action
from app.intelligence.reporting import business_snapshot, fingerprint, metric_fingerprint
from app.models import (Experiment, ExperimentDesign, GrowthRecommendation, GrowthStrategyRun,
                        InvestigationRun, KnowledgeChunk, Membership, RecommendationApproval)


def require_current_design(db, context, workspace, experiment: Experiment) -> None:
    """Keep the approved design within today's tenant context and evidence limits."""
    design = db.scalar(select(ExperimentDesign).where(
        ExperimentDesign.workspace_id == context.workspace_id,
        ExperimentDesign.experiment_id == experiment.id,
    ))
    if design is None:
        return  # Existing manually created simulation drafts keep their established path.
    if (experiment.action_type != "simulation_only" or design.experiment_version != experiment.version
            or experiment.status not in {"draft", "approved"}):
        raise HTTPException(409, "Experiment design does not match this simulation version")

    recommendation = db.scalar(select(GrowthRecommendation).where(
        GrowthRecommendation.id == design.recommendation_id,
        GrowthRecommendation.workspace_id == context.workspace_id,
    ))
    strategy = db.scalar(select(GrowthStrategyRun).where(
        GrowthStrategyRun.id == recommendation.strategy_run_id,
        GrowthStrategyRun.workspace_id == context.workspace_id,
    )) if recommendation else None
    approval = db.scalar(select(RecommendationApproval).join(Membership, (
        Membership.workspace_id == RecommendationApproval.workspace_id
    ) & (Membership.user_id == RecommendationApproval.approved_by_user_id)).where(
        RecommendationApproval.id == design.recommendation_approval_id,
        RecommendationApproval.workspace_id == context.workspace_id,
        RecommendationApproval.recommendation_id == design.recommendation_id,
        RecommendationApproval.recommendation_version == (recommendation.version if recommendation else -1),
        Membership.role == "owner",
    ))
    if (recommendation is None or strategy is None or approval is None or recommendation.status != "approved"
            or (context.constraints and not approval.constraints_acknowledged)):
        raise HTTPException(409, "Designed simulation requires a current owner-approved recommendation")
    if fingerprint(business_snapshot(context, workspace.currency)) != fingerprint(strategy.context_snapshot):
        raise HTTPException(409, "Business goals, budget, constraints or industry configuration changed; redesign the experiment")

    action = recommendation.content.get("action_type", "")
    cost = Decimal(str(design.design.get("estimated_cost", "-1")))
    if (action not in context.industry_pack.experiment_types or blocked_action(context, action)
            or cost < 0 or cost > Decimal(str(context.monthly_budget))):
        raise HTTPException(409, "Current business constraints or budget block this experiment design")

    investigation = db.scalar(select(InvestigationRun).where(
        InvestigationRun.id == strategy.investigation_id,
        InvestigationRun.workspace_id == context.workspace_id,
    ))
    if investigation is None:
        raise HTTPException(409, "Experiment investigation evidence is unavailable; create a new design")
    period = investigation.result.get("reporting_period", {})
    try:
        start = date.fromisoformat(period["start"])
        end = date.fromisoformat(period["end"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409, "Experiment investigation has no valid financial reporting period") from None
    full_report = dashboard(db, workspace, context.industry_pack, start, end)
    if metric_fingerprint(full_report) != investigation.result.get("metric_snapshot_digest"):
        raise HTTPException(409, "Investigation financial evidence changed; create a new design")
    source_ids = {item["id"] for item in investigation.result.get("evidence_sources", [])}
    if source_ids and set(db.scalars(select(KnowledgeChunk.id).where(
        KnowledgeChunk.workspace_id == context.workspace_id, KnowledgeChunk.id.in_(source_ids),
    ))) != source_ids:
        raise HTTPException(409, "Investigation source documents are unavailable; create a new design")

    try:
        baseline_start = date.fromisoformat(design.design["baseline"]["start"])
        baseline_end = date.fromisoformat(design.design["baseline"]["end"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409, "Experiment baseline is invalid; create a new design") from None
    current_baseline = dashboard(db, workspace, context.industry_pack, baseline_start, baseline_end)
    if metric_fingerprint(current_baseline) != design.design["baseline"].get("metric_snapshot_digest"):
        raise HTTPException(409, "Experiment baseline data changed; create a new design")
