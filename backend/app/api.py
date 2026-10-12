import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.analytics import MAX_UPLOAD_BYTES, dashboard, parse_csv
from app.auth import CurrentUser, DUMMY_HASH, Db, Tenant, password_hasher, set_session
from app.intelligence.context import verified_business_context
from app.intelligence.audit import record_audit
from app.intelligence.documents import save_document, search_documents
from app.intelligence.evidence import DataIntelligenceAgent
from app.intelligence.investigation import InvestigationAgent, InvestigationError
from app.config import get_settings
from app.industries import PACKS
from app.models import DailyMetric, InvestigationRun, KnowledgeChunk, KnowledgeDocument, Membership, User, Workspace
from app.schemas import BusinessProfile, InvestigationRequest, KnowledgeSearch, Login, ProfileUpdate, Register

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


@router.post("/auth/register", status_code=201)
def register(payload: Register, response: Response, db: Db):
    user = User(email=payload.email, password_hash=password_hasher.hash(payload.password))
    workspace = Workspace(name=payload.business_name.strip(), industry=payload.industry)
    if len(workspace.name) < 2:
        raise HTTPException(422, "Business name must have at least two characters")
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
def login(payload: Login, response: Response, db: Db):
    user = db.scalar(select(User).where(User.email == payload.email))
    verified = password_hasher.verify(payload.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not verified:
        raise HTTPException(401, "Invalid email or password")
    set_session(response, user.id)
    return {"email": user.email}


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie("marketmind_session", path="/")


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
def get_dashboard(workspace: Tenant, db: Db):
    return dashboard(db, workspace, PACKS[workspace.industry])


@router.post("/data/import")
async def import_data(file: UploadFile, workspace: Tenant, db: Db):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "CSV limit is 2 MB")
    records = parse_csv(content, PACKS[workspace.industry])
    existing = {row.day: row for row in db.scalars(select(DailyMetric).where(
        DailyMetric.workspace_id == workspace.id, DailyMetric.day.in_([day for day, _ in records]))).all()}
    for day, values in records:
        if day in existing:
            existing[day].values = values
        else:
            db.add(DailyMetric(workspace_id=workspace.id, day=day, values=values))
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
    return {"embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model if embeddings_enabled else None,
            "investigation_provider": settings.investigation_provider,
            "investigation_model": settings.investigation_model if investigation_enabled else None,
            "external_processing": embeddings_enabled or investigation_enabled,
            "retrieval_mode": "hybrid" if embeddings_enabled and db.get_bind().dialect.name == "postgresql" else "lexical"}


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
