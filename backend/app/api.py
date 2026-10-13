import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

from app.analytics import MAX_UPLOAD_BYTES, dashboard, parse_csv
from app.auth import CurrentUser, DUMMY_HASH, Db, Tenant, password_hasher, set_session
from app.auth_limits import limit_auth
from app.intelligence.context import verified_business_context
from app.intelligence.audit import record_audit
from app.intelligence.documents import save_document, search_documents
from app.intelligence.evidence import DataIntelligenceAgent
from app.intelligence.experiment_guard import require_current_design
from app.intelligence.experiment_state import transition_dispatch, transition_experiment
from app.intelligence.investigation import InvestigationAgent, InvestigationError
from app.integrations.n8n import DatabaseApprovalVerifier, DispatchOutcome, N8nExecutor
from app.config import get_settings
from app.db import set_db_scope
from app.industries import PACKS
from app.models import (DailyMetric, Experiment, ExperimentApproval, InvestigationRun, KnowledgeChunk,
                        KnowledgeDocument, Membership, N8nDispatch, User, Workspace)
from app.schemas import (BusinessProfile, ExperimentCreate, InvestigationRequest, KnowledgeSearch,
                         Login, ProfileUpdate, Register)

router = APIRouter(prefix="/api")
data_intelligence_agent = DataIntelligenceAgent()
investigation_agent = InvestigationAgent(data_intelligence_agent)


def require_context(db: Db, user: CurrentUser, workspace: Workspace):
    try:
        return verified_business_context(db, user, workspace.id)
    except PermissionError:
        raise HTTPException(403, "Workspace access denied") from None


def document_summary(document: KnowledgeDocument) -> dict:
    return {"id": document.id, "name": document.name, "mime_type": document.mime_type,
            "character_count": document.character_count, "created_at": document.created_at}


def digest_text(value: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def configured_n8n_executor(db: Db) -> N8nExecutor:
    settings = get_settings()
    if not settings.n8n_webhook_url or not settings.n8n_webhook_token:
        raise HTTPException(503, "n8n Cloud webhook is not configured")
    try:
        return N8nExecutor(settings.n8n_webhook_url, settings.n8n_webhook_token.get_secret_value(),
                           DatabaseApprovalVerifier(db))
    except ValueError:
        raise HTTPException(503, "n8n Cloud webhook configuration is invalid") from None


def require_workspace_owner(db: Db, user: CurrentUser, workspace: Workspace) -> Membership:
    membership = db.scalar(select(Membership).where(
        Membership.workspace_id == workspace.id, Membership.user_id == user.id,
    ))
    if membership is None or membership.role != "owner":
        raise HTTPException(403, "Workspace owner access required")
    return membership


def check_simulation_constraints(db: Db, context, user: CurrentUser, workspace: Workspace) -> None:
    constraints = [str(item).casefold() for item in (workspace.constraints or [])]
    blocked = ("no automation", "no n8n", "no experiment", "disable simulation", "simulation disabled")
    if workspace.monthly_budget < 0 or any(marker in item for item in constraints for marker in blocked):
        record_audit(db, context, user.id, "experiment.approval_blocked", "experiment", None,
                     {"reason": "workspace_budget_or_constraint"})
        db.commit()
        raise HTTPException(409, "Workspace budget or constraints block this simulation")


def dispatch_view(dispatch: N8nDispatch, approval_id: str) -> dict:
    completion_status = ("completed" if dispatch.status == "completed" else
                         "failed" if dispatch.status == "execution_failed" else "not_reported")
    return {"experiment_id": dispatch.experiment_id,
            "experiment_status": dispatch.status if completion_status != "not_reported" else "approved",
            "approval_id": approval_id, "execution_id": dispatch.execution_id,
            "dispatch_status": dispatch.status, "http_status": dispatch.http_status,
            "failure_code": dispatch.failure_code,
            "completion_status": completion_status,
            "message": ("n8n acknowledged receipt; this does not confirm workflow or experiment success."
                        if dispatch.status == "acknowledged" else
                        "Dispatch failed and will not be resent automatically."
                        if dispatch.status == "failed" else
                        "The simulation reported completion; this is not a real business outcome."
                        if dispatch.status == "completed" else
                        "The simulation reported failure; this is not a real business outcome."
                        if dispatch.status == "execution_failed" else
                        "Dispatch is already reserved; no duplicate webhook was sent.")}


@router.post("/auth/register", status_code=201)
def register(payload: Register, request: Request, response: Response, db: Db):
    limit_auth(db, request, payload.email, registration=True)
    user = User(id=str(uuid.uuid4()), email=payload.email, password_hash=password_hasher.hash(payload.password))
    workspace = Workspace(id=str(uuid.uuid4()), name=payload.business_name.strip(), industry=payload.industry)
    if len(workspace.name) < 2:
        raise HTTPException(422, "Business name must have at least two characters")
    set_db_scope(db, workspace_id=workspace.id, user_id=user.id)
    db.add_all([user, workspace])
    try:
        db.flush()
        db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account could not be created with this email") from None
    set_session(response, user.id)
    return {"email": user.email, "workspace_id": workspace.id}


@router.post("/auth/login")
def login(payload: Login, request: Request, response: Response, db: Db):
    limit_auth(db, request, payload.email, registration=False)
    user = db.scalar(select(User).where(User.email == payload.email))
    verified = password_hasher.verify(payload.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not verified:
        raise HTTPException(401, "Invalid email or password")
    set_session(response, user.id)
    return {"email": user.email}


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie("marketmind_session", path="/", httponly=True,
                           secure=get_settings().cookie_secure, samesite="lax")


@router.get("/auth/me")
def me(user: CurrentUser, db: Db):
    workspaces = db.scalars(select(Workspace).join(Membership).where(Membership.user_id == user.id)).all()
    return {"id": user.id, "email": user.email,
            "workspaces": [{"id": row.id, "name": row.name, "industry": row.industry} for row in workspaces]}


@router.get("/industry-packs")
def industry_packs():
    return [pack.public() for pack in PACKS.values()]


@router.get("/business", response_model=BusinessProfile)
def get_business(workspace: Tenant):
    return workspace


@router.put("/business", response_model=BusinessProfile)
def update_business(payload: ProfileUpdate, workspace: Tenant, db: Db):
    if len(payload.name.strip()) < 2:
        raise HTTPException(422, "Business name must have at least two characters")
    if payload.currency != workspace.currency and db.scalar(
        select(DailyMetric.id).where(DailyMetric.workspace_id == workspace.id).limit(1)
    ):
        raise HTTPException(409, "Currency cannot change after importing data")
    for key, value in payload.model_dump().items():
        setattr(workspace, key, value.strip() if key == "name" else value)
    db.commit()
    return workspace


@router.get("/dashboard")
def get_dashboard(workspace: Tenant, db: Db, start_date: date | None = None, end_date: date | None = None):
    if (start_date is None) != (end_date is None):
        raise HTTPException(422, "Provide both start_date and end_date for a reporting period")
    if start_date and (end_date - start_date).days > 365:
        raise HTTPException(422, "A reporting period cannot exceed 366 calendar days")
    try:
        return dashboard(db, workspace, PACKS[workspace.industry], start_date, end_date)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/data/import")
async def import_data(file: UploadFile, workspace: Tenant, db: Db):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "CSV limit is 2 MB")
    records = parse_csv(content, PACKS[workspace.industry])
    existing = {row.day: row for row in db.scalars(select(DailyMetric).where(
        DailyMetric.workspace_id == workspace.id, DailyMetric.day.in_([day for day, _, _ in records]))).all()}
    pack = PACKS[workspace.industry]
    for day, values, schema_version in records:
        variable_costs = sum((Decimal(str(values.get(key, "0"))) for key in (
            pack.cost_column, "fulfillment_cost", "payment_fees", "other_variable_costs",
        )), Decimal("0"))
        metrics = {
            "schema_version": schema_version,
            "gross_revenue": Decimal(str(values["revenue"])),
            "refunds": Decimal(str(values.get("refunds", "0"))),
            "ad_spend": Decimal(str(values["ad_spend"])),
            "variable_costs": variable_costs,
            "fixed_costs": Decimal(str(values.get("fixed_costs", "0"))),
            "orders": values.get("orders"),
            "fulfilled_orders": values.get("fulfilled_orders"),
            "cancelled_orders": values.get("cancelled_orders"),
            "delayed_orders": values.get("delayed_orders"),
            "bookings": values.get("bookings"),
            "completed_appointments": values.get("completed"),
            "cancelled_appointments": values.get("cancelled"),
        }
        if day in existing:
            existing[day].values = values
            for field, value in metrics.items():
                setattr(existing[day], field, value)
        else:
            db.add(DailyMetric(workspace_id=workspace.id, day=day, values=values, **metrics))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An import for these dates is already running; retry") from None
    return {"imported_rows": len(records), "message": "Daily totals saved. Existing dates were replaced."}


@router.get("/knowledge/documents")
def list_documents(workspace: Tenant, db: Db, user: CurrentUser):
    context = require_context(db, user, workspace)
    documents = db.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.workspace_id == context.workspace_id,
    ).order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id).limit(500)).all()
    return [document_summary(document) for document in documents]


@router.get("/knowledge/retrieval")
def retrieval_configuration(workspace: Tenant, db: Db, user: CurrentUser):
    require_context(db, user, workspace)
    settings = get_settings()
    embeddings_enabled = settings.embedding_provider != "disabled"
    investigation_enabled = settings.investigation_provider != "disabled"
    strategy_enabled = settings.strategy_provider != "disabled"
    return {"embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model if embeddings_enabled else None,
            "investigation_provider": settings.investigation_provider,
            "investigation_model": settings.investigation_model if investigation_enabled else None,
            "strategy_provider": settings.strategy_provider,
            "strategy_model": settings.investigation_model if strategy_enabled else None,
            "external_processing": embeddings_enabled or investigation_enabled or strategy_enabled,
            "retrieval_mode": "hybrid" if embeddings_enabled and db.get_bind().dialect.name == "postgresql" else "lexical"}


@router.post("/experiments", status_code=201)
def create_experiment(payload: ExperimentCreate, workspace: Tenant, db: Db, user: CurrentUser):
    require_workspace_owner(db, user, workspace)
    business_context = require_context(db, user, workspace)
    experiment = Experiment(workspace_id=workspace.id, created_by_user_id=user.id, name=payload.name,
                            action_type=payload.action_type, status="draft", version=1,
                            metadata_json=payload.metadata.model_dump())
    db.add(experiment)
    db.flush()
    record_audit(db, business_context, user.id, "experiment.created", "experiment",
                 experiment.id, {"version": experiment.version, "action_type": experiment.action_type})
    db.commit()
    return {"id": experiment.id, "name": experiment.name, "status": experiment.status,
            "action_type": experiment.action_type, "version": experiment.version}


@router.post("/experiments/{experiment_id}/approve")
def approve_experiment(experiment_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    business_context = require_context(db, user, workspace)
    require_workspace_owner(db, user, workspace)
    experiment = db.scalar(select(Experiment).where(
        Experiment.id == experiment_id, Experiment.workspace_id == workspace.id,
    ).with_for_update())
    if experiment is None:
        raise HTTPException(404, "Experiment not found")
    if experiment.created_by_user_id != user.id:
        raise HTTPException(403, "Only the experiment owner who created it can approve it")
    check_simulation_constraints(db, business_context, user, workspace)
    executor = None
    if experiment.status == "draft":
        require_current_design(db, business_context, workspace, experiment)
        executor = configured_n8n_executor(db)
        approval = ExperimentApproval(workspace_id=workspace.id, experiment_id=experiment.id,
                                      experiment_version=experiment.version,
                                      approved_by_user_id=user.id, status="approved")
        transition_experiment(experiment, "approved")
        db.add(approval)
        db.flush()
        record_audit(db, business_context, user.id, "experiment.approved", "experiment",
                     experiment.id, {"approval_id": approval.id, "version": experiment.version})
        db.commit()
    elif experiment.status == "approved":
        approval = db.scalar(select(ExperimentApproval).where(
            ExperimentApproval.workspace_id == workspace.id,
            ExperimentApproval.experiment_id == experiment.id,
            ExperimentApproval.experiment_version == experiment.version,
            ExperimentApproval.approved_by_user_id == user.id,
            ExperimentApproval.status == "approved",
        ))
        if approval is None:
            raise HTTPException(409, "No valid owner approval exists for this experiment version")
    elif experiment.status in {"completed", "execution_failed"}:
        approval = db.scalar(select(ExperimentApproval).where(
            ExperimentApproval.workspace_id == workspace.id,
            ExperimentApproval.experiment_id == experiment.id,
            ExperimentApproval.experiment_version == experiment.version,
            ExperimentApproval.approved_by_user_id == user.id,
            ExperimentApproval.status == "approved",
        ))
        if approval is None:
            raise HTTPException(409, "No valid owner approval exists for this experiment version")
    else:
        raise HTTPException(409, "Experiment is not in an approvable state")

    idempotency_key = f"{workspace.id}:{experiment.id}:v{experiment.version}"
    dispatch = db.scalar(select(N8nDispatch).where(
        N8nDispatch.workspace_id == workspace.id, N8nDispatch.idempotency_key == idempotency_key,
    ))
    if dispatch is not None:
        record_audit(db, business_context, user.id, "n8n.dispatch_duplicate", "experiment",
                     experiment.id, {"execution_id": dispatch.execution_id, "status": dispatch.status})
        db.commit()
        return dispatch_view(dispatch, approval.id)

    if executor is None:
        require_current_design(db, business_context, workspace, experiment)
        executor = configured_n8n_executor(db)
    dispatch = N8nDispatch(workspace_id=workspace.id, experiment_id=experiment.id,
                           approval_id=approval.id, idempotency_key=idempotency_key, status="dispatching")
    db.add(dispatch)
    try:
        db.flush()
        execution_id = dispatch.execution_id
        record_audit(db, business_context, user.id, "n8n.dispatch_started", "experiment",
                     experiment.id, {"execution_id": execution_id, "approval_id": approval.id,
                                     "action_type": experiment.action_type})
        db.commit()
    except IntegrityError:
        db.rollback()
        dispatch = db.scalar(select(N8nDispatch).where(
            N8nDispatch.workspace_id == workspace.id, N8nDispatch.idempotency_key == idempotency_key,
        ))
        if dispatch is None:
            raise HTTPException(409, "Dispatch reservation conflicted; no webhook was sent") from None
        return dispatch_view(dispatch, approval.id)

    try:
        outcome = executor.execute(business_context, experiment.id, approval.id, experiment.version,
                                   execution_id, experiment.action_type, experiment.metadata_json,
                                   idempotency_key, approval.approved_at)
    except PermissionError:
        outcome = DispatchOutcome("failed", None, "approval_recheck_failed")
    dispatch = db.scalar(select(N8nDispatch).where(
        N8nDispatch.workspace_id == workspace.id, N8nDispatch.execution_id == execution_id,
    ).with_for_update().execution_options(populate_existing=True))
    callback_already_terminal = dispatch.status in {"completed", "execution_failed"}
    if not callback_already_terminal:
        transition_dispatch(dispatch, outcome.status)
    dispatch.http_status = outcome.http_status
    if not callback_already_terminal:
        dispatch.failure_code = outcome.failure_code
    if outcome.status == "acknowledged" and not dispatch.acknowledged_at:
        dispatch.acknowledged_at = datetime.now(timezone.utc)
    record_audit(db, business_context, user.id,
                 "n8n.webhook_acknowledged" if outcome.status == "acknowledged" else "n8n.webhook_failed",
                 "experiment", experiment.id,
                 {"execution_id": execution_id, "http_status": outcome.http_status,
                  "failure_code": outcome.failure_code,
                  "completion_status": "not_reported" if not callback_already_terminal else dispatch.status})
    db.commit()
    return dispatch_view(dispatch, approval.id)


@router.post("/experiments/{experiment_id}/reject")
def reject_experiment(experiment_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    business_context = require_context(db, user, workspace)
    require_workspace_owner(db, user, workspace)
    experiment = db.scalar(select(Experiment).where(
        Experiment.id == experiment_id, Experiment.workspace_id == workspace.id,
    ).with_for_update())
    if experiment is None:
        raise HTTPException(404, "Experiment not found")
    if experiment.created_by_user_id != user.id:
        raise HTTPException(403, "Only the experiment owner who created it can reject it")
    if experiment.status != "draft":
        raise HTTPException(409, "Only a draft experiment can be rejected")
    transition_experiment(experiment, "rejected")
    record_audit(db, business_context, user.id, "experiment.rejected", "experiment",
                 experiment.id, {"version": experiment.version})
    db.commit()
    return {"id": experiment.id, "status": experiment.status, "version": experiment.version}


@router.post("/knowledge/documents", status_code=201)
async def add_document(file: UploadFile, workspace: Tenant, db: Db, user: CurrentUser):
    content_context = require_context(db, user, workspace)
    try:
        return document_summary(await save_document(db, content_context, file, user.id))
    finally:
        await file.close()


@router.delete("/knowledge/documents/{document_id}", status_code=204)
def delete_document(document_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    content_context = require_context(db, user, workspace)
    document = db.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.id == document_id,
        KnowledgeDocument.workspace_id == content_context.workspace_id,
    ))
    if document is None:
        raise HTTPException(404, "Document not found")
    db.query(KnowledgeChunk).filter(
        KnowledgeChunk.document_id == document.id,
        KnowledgeChunk.workspace_id == content_context.workspace_id,
    ).delete(synchronize_session=False)
    db.delete(document)
    record_audit(db, content_context, user.id, "knowledge.document.deleted", "knowledge_document",
                 document_id, {"sha256": document.sha256})
    db.commit()


@router.post("/knowledge/search")
def search_knowledge(payload: KnowledgeSearch, workspace: Tenant, db: Db, user: CurrentUser):
    content_context = require_context(db, user, workspace)
    try:
        results = search_documents(db, content_context, payload.query, payload.limit)
    except HTTPException as exc:
        if exc.status_code == 503:
            record_audit(db, content_context, user.id, "knowledge.embedding.failed", "knowledge_query", None,
                         {"query_digest": digest_text(payload.query), "failure": "provider_or_vector_validation"})
            db.commit()
        raise
    record_audit(db, content_context, user.id, "knowledge.search", "knowledge_query", None,
                 {"query_digest": digest_text(payload.query), "result_count": len(results),
                  "retrieval_methods": sorted({method for result in results for method in result["retrieval_methods"]}),
                  "embedding_provider": get_settings().embedding_provider})
    db.commit()
    return {"query": payload.query, "results": results}


@router.post("/investigations", status_code=201)
def start_investigation(payload: InvestigationRequest, workspace: Tenant, db: Db, user: CurrentUser):
    content_context = require_context(db, user, workspace)
    try:
        analysis = investigation_agent.investigate(db, content_context, payload.question)
    except InvestigationError as exc:
        if get_settings().investigation_provider != "disabled":
            record_audit(db, content_context, user.id, "investigation.failed", "investigation", None,
                         {"question_digest": digest_text(payload.question), "failure": "provider_or_output_validation"})
            db.commit()
        raise HTTPException(503, str(exc)) from None
    run = InvestigationRun(workspace_id=content_context.workspace_id, question=payload.question,
                           status=analysis["status"], result=analysis["result"], model=analysis["model"],
                           prompt_version=analysis["prompt_version"], input_tokens=analysis["input_tokens"],
                           output_tokens=analysis["output_tokens"], confidence=analysis["confidence"],
                           estimated_cost_usd=analysis["estimated_cost_usd"], cost_schedule=analysis["cost_schedule"])
    db.add(run)
    record_audit(db, content_context, user.id,
                 "investigation.analyzed" if analysis["model"] else "investigation.evidence_reviewed",
                 "investigation", run.id,
                 {"question_digest": digest_text(payload.question), "status": analysis["status"],
                  "model": analysis["model"], "prompt_version": analysis["prompt_version"],
                  "input_tokens": analysis["input_tokens"], "output_tokens": analysis["output_tokens"],
                  "estimated_cost_usd": str(analysis["estimated_cost_usd"]) if analysis["estimated_cost_usd"] is not None else None,
                  "cost_schedule": analysis["cost_schedule"]})
    db.commit()
    db.refresh(run)
    return {"id": run.id, "question": run.question, "status": run.status,
            "created_at": run.created_at, "result": run.result,
            "confidence": run.confidence, "model": run.model, "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens, "estimated_cost_usd": run.estimated_cost_usd,
            "cost_schedule": run.cost_schedule, "prompt_version": run.prompt_version}


@router.get("/investigations")
def list_investigations(workspace: Tenant, db: Db, user: CurrentUser):
    content_context = require_context(db, user, workspace)
    runs = db.scalars(select(InvestigationRun).where(
        InvestigationRun.workspace_id == content_context.workspace_id,
    ).order_by(InvestigationRun.created_at.desc(), InvestigationRun.id).limit(100)).all()
    return [{"id": run.id, "question": run.question, "status": run.status,
             "created_at": run.created_at, "evidence_count": len(run.result["findings"]),
             "model": run.model, "confidence": run.confidence} for run in runs]


@router.get("/investigations/{run_id}")
def get_investigation(run_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    content_context = require_context(db, user, workspace)
    run = db.scalar(select(InvestigationRun).where(
        InvestigationRun.id == run_id, InvestigationRun.workspace_id == content_context.workspace_id,
    ))
    if run is None:
        raise HTTPException(404, "Investigation not found")
    return {"id": run.id, "question": run.question, "status": run.status,
            "created_at": run.created_at, "result": run.result,
            "confidence": run.confidence, "model": run.model, "prompt_version": run.prompt_version,
            "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
            "estimated_cost_usd": run.estimated_cost_usd, "cost_schedule": run.cost_schedule}
