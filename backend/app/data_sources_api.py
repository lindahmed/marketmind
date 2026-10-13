"""Workspace data-source management and n8n push ingestion routes."""
import hashlib
import hmac
import secrets

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError

from app.auth import CurrentUser, Db, Tenant
from app.intelligence.audit import record_audit
from app.models import BusinessEvent, DataImportRun, DataSource, Membership, ReconciliationDecision, Workspace
from app.reconciliation import record_batch
from app.schemas import ConflictResolutionInput, DataSourceBatch, DataSourceCreate

router = APIRouter(prefix="/api")


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_view(source: DataSource) -> dict:
    return {"id": source.id, "provider": source.provider, "source_identifier": source.source_identifier,
            "name": source.name, "status": source.status, "sync_status": source.sync_status,
            "last_sync_at": source.last_sync_at, "created_at": source.created_at}


def _run_view(run: DataImportRun) -> dict:
    return {"id": run.id, "source_id": run.source_id, "request_id": run.request_id, "status": run.status,
            "received_count": run.received_count, "accepted_count": run.accepted_count,
            "duplicate_count": run.duplicate_count, "conflict_count": run.conflict_count,
            "missing_count": run.missing_count, "deleted_count": run.deleted_count, "started_at": run.started_at,
            "finished_at": run.finished_at, "error_code": run.error_code}


def _owner(db, user, workspace):
    membership = db.scalar(select(Membership).where(Membership.workspace_id == workspace.id,
                                                       Membership.user_id == user.id))
    if membership is None or membership.role != "owner":
        raise HTTPException(403, "Workspace owner access required")


@router.post("/data-sources", status_code=201)
def create_source(payload: DataSourceCreate, workspace: Tenant, user: CurrentUser, db: Db):
    _owner(db, user, workspace)
    if len(payload.name.strip()) < 2 or not payload.source_identifier.strip():
        raise HTTPException(422, "Source name and identifier cannot be blank")
    token = secrets.token_urlsafe(32)
    source = DataSource(workspace_id=workspace.id, provider=payload.provider,
                        source_identifier=payload.source_identifier.strip(), name=payload.name.strip(),
                        secret_hash=_hash_secret(token), created_by_user_id=user.id)
    db.add(source)
    try:
        db.flush()
        context = type("WorkspaceContext", (), {"workspace_id": workspace.id})()
        record_audit(db, context, user.id, "data_source.created", "data_source", source.id,
                     {"provider": source.provider})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A source with this identifier already exists in the workspace") from None
    return {**_source_view(source), "ingestion_token": token,
            "token_notice": "Copy this token into the n8n credential now. It cannot be retrieved later."}


@router.get("/data-sources")
def list_sources(workspace: Tenant, db: Db):
    sources = db.scalars(select(DataSource).where(DataSource.workspace_id == workspace.id)
                         .order_by(DataSource.created_at.desc(), DataSource.id)).all()
    return [_source_view(source) for source in sources]


@router.get("/data-sources/quality")
def data_quality(workspace: Tenant, db: Db):
    sources = db.scalars(select(DataSource).where(DataSource.workspace_id == workspace.id)).all()
    runs = db.scalars(select(DataImportRun).where(DataImportRun.workspace_id == workspace.id)
                      .order_by(desc(DataImportRun.started_at), desc(DataImportRun.id)).limit(100)).all()
    decisions = db.scalars(select(ReconciliationDecision).where(ReconciliationDecision.workspace_id == workspace.id)
                           .order_by(desc(ReconciliationDecision.created_at), desc(ReconciliationDecision.id))
                           .limit(100)).all()
    conflicts = db.scalars(select(BusinessEvent).where(
        BusinessEvent.workspace_id == workspace.id,
        BusinessEvent.reconciliation_status.in_(("conflict", "missing")),
    ).order_by(desc(BusinessEvent.created_at), desc(BusinessEvent.id)).limit(500)).all()
    accepted_filter = (BusinessEvent.workspace_id == workspace.id,
                       BusinessEvent.reconciliation_status == "accepted", BusinessEvent.is_current.is_(True))
    required_types = ({"order", "payment", "refund", "fulfillment", "cancellation", "marketing_spend", "expense"}
                      if workspace.industry == "ecommerce" else
                      {"appointment_outcome", "payment", "refund", "marketing_spend", "expense"})
    event_types = set(db.scalars(select(BusinessEvent.event_type).where(*accepted_filter).distinct()).all())
    campaign_rows = db.execute(select(BusinessEvent.campaign_id, func.sum(BusinessEvent.amount)).where(
        *accepted_filter, BusinessEvent.event_type == "payment", BusinessEvent.status_value == "captured",
        BusinessEvent.campaign_id.is_not(None)).group_by(BusinessEvent.campaign_id)).all()
    campaign_payments = {campaign_id: float(total or 0) for campaign_id, total in campaign_rows}
    unmatched_payments = float(db.scalar(select(func.sum(BusinessEvent.amount)).where(
        *accepted_filter, BusinessEvent.event_type == "payment", BusinessEvent.status_value == "captured",
        BusinessEvent.campaign_id.is_(None))) or 0)
    matched_ids = {event.matched_event_id for event in conflicts if event.matched_event_id}
    existing_records = {event.id: event for event in db.scalars(select(BusinessEvent).where(
        BusinessEvent.workspace_id == workspace.id, BusinessEvent.id.in_(matched_ids))).all()} if matched_ids else {}
    return {"source_count": len(sources), "sources": [_source_view(source) for source in sources],
            "imports": [_run_view(run) for run in runs],
            "conflicts": [{"id": event.id, "source_id": event.source_id,
                           "source_event_id": event.source_event_id, "event_type": event.event_type,
                           "entity_id": event.entity_id, "occurred_at": event.occurred_at,
                           "status": event.reconciliation_status, "note": event.reconciliation_note,
                           "amount": float(event.amount) if event.amount is not None else None,
                           "currency": event.currency, "status_value": event.status_value,
                           "campaign_id": event.campaign_id, "channel": event.channel,
                           "matched_event_id": event.matched_event_id,
                           "existing_record": ({"amount": float(existing_records[event.matched_event_id].amount)
                                                if existing_records[event.matched_event_id].amount is not None else None,
                                                "currency": existing_records[event.matched_event_id].currency,
                                                "status_value": existing_records[event.matched_event_id].status_value,
                                                "campaign_id": existing_records[event.matched_event_id].campaign_id}
                                               if event.reconciliation_status == "conflict"
                                               and event.matched_event_id in existing_records else None),
                           "provenance": event.provenance} for event in conflicts],
            "reconciliation": {"accepted_events": db.query(BusinessEvent).filter(
                BusinessEvent.workspace_id == workspace.id, BusinessEvent.reconciliation_status == "accepted",
                BusinessEvent.is_current.is_(True)).count(),
                "duplicate_events": db.query(BusinessEvent).filter(
                    BusinessEvent.workspace_id == workspace.id, BusinessEvent.reconciliation_status == "duplicate").count(),
                "conflicting_events": db.scalar(select(func.count()).select_from(BusinessEvent).where(
                    BusinessEvent.workspace_id == workspace.id,
                    BusinessEvent.reconciliation_status == "conflict")) or 0,
                "records_missing_required_fields": db.scalar(select(func.count()).select_from(BusinessEvent).where(
                    BusinessEvent.workspace_id == workspace.id,
                    BusinessEvent.reconciliation_status == "missing")) or 0},
            "decisions": [{"id": item.id, "conflict_event_id": item.conflict_event_id,
                           "selected_event_id": item.selected_event_id, "decision": item.decision,
                           "note": item.note, "provenance": item.provenance, "created_at": item.created_at}
                          for item in decisions],
            "event_coverage": {"observed_event_types": sorted(event_types),
                               "missing_event_types": sorted(required_types - event_types)},
            "recorded_campaign_payments": dict(sorted(campaign_payments.items())),
            "payments_without_campaign_id": unmatched_payments,
            "campaign_note": "Campaign identifiers are source labels only and do not establish advertising causality or attribution."}


@router.get("/data-sources/{source_id}/imports")
def source_imports(source_id: str, workspace: Tenant, db: Db):
    source = db.scalar(select(DataSource).where(DataSource.id == source_id,
                                                  DataSource.workspace_id == workspace.id))
    if source is None:
        raise HTTPException(404, "Data source not found")
    runs = db.scalars(select(DataImportRun).where(DataImportRun.source_id == source.id)
                      .order_by(desc(DataImportRun.started_at), desc(DataImportRun.id)).limit(100)).all()
    return [_run_view(run) for run in runs]


@router.post("/data-sources/{source_id}/revoke", status_code=204)
def revoke_source(source_id: str, workspace: Tenant, user: CurrentUser, db: Db):
    _owner(db, user, workspace)
    source = db.scalar(select(DataSource).where(DataSource.id == source_id,
                                                  DataSource.workspace_id == workspace.id))
    if source is None:
        raise HTTPException(404, "Data source not found")
    source.status = "revoked"
    source.sync_status = "revoked"
    context = type("WorkspaceContext", (), {"workspace_id": workspace.id})()
    record_audit(db, context, user.id, "data_source.revoked", "data_source", source.id, {})
    db.commit()
    return None


@router.post("/data-sources/{source_id}/rotate-token")
def rotate_source_token(source_id: str, workspace: Tenant, user: CurrentUser, db: Db):
    _owner(db, user, workspace)
    source = db.scalar(select(DataSource).where(DataSource.id == source_id,
                                                  DataSource.workspace_id == workspace.id))
    if source is None:
        raise HTTPException(404, "Data source not found")
    token = secrets.token_urlsafe(32)
    source.secret_hash = _hash_secret(token)
    source.status = "active"
    context = type("WorkspaceContext", (), {"workspace_id": workspace.id})()
    record_audit(db, context, user.id, "data_source.token_rotated", "data_source", source.id, {})
    db.commit()
    return {**_source_view(source), "ingestion_token": token,
            "token_notice": "Copy this replacement token into the n8n credential now. It cannot be retrieved later."}


@router.post("/integrations/google-sheets/{source_id}/ingest")
def ingest_sheets(source_id: str, payload: DataSourceBatch, db: Db,
                  authorization: str | None = Header(default=None)):
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise HTTPException(401, "Source bearer token required")
    source = db.get(DataSource, source_id)
    if (source is None or source.provider != "google_sheets" or source.status != "active"
            or not hmac.compare_digest(source.secret_hash, _hash_secret(token))):
        raise HTTPException(401, "Invalid source credentials")
    workspace = db.get(Workspace, source.workspace_id)
    if workspace is None:
        raise HTTPException(401, "Invalid source credentials")
    currencies = {event.currency for event in payload.records if event.currency}
    if currencies - {workspace.currency}:
        raise HTTPException(422, "Imported event currencies must match the workspace currency")
    try:
        run, replay = record_batch(db, source, payload, workspace.industry)
        context = type("WorkspaceContext", (), {"workspace_id": source.workspace_id})()
        record_audit(db, context, None, "data_source.imported", "data_import_run", run.id,
                     {"source_id": source.id, "status": run.status, "received": run.received_count,
                      "accepted": run.accepted_count, "duplicates": run.duplicate_count,
                      "conflicts": run.conflict_count, "missing": run.missing_count})
        db.commit()
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An import with this request ID is already being processed") from None
    return {**_run_view(run), "replayed": replay}


@router.post("/data-sources/conflicts/{event_id}/resolve")
def resolve_conflict(event_id: str, payload: ConflictResolutionInput, workspace: Tenant, user: CurrentUser, db: Db):
    _owner(db, user, workspace)
    def replay_or_reject(prior_decision):
        if prior_decision.decision == payload.decision:
            return {"decision_id": prior_decision.id, "conflict_event_id": event_id,
                    "selected_event_id": prior_decision.selected_event_id,
                    "decision": prior_decision.decision, "replayed": True}
        raise HTTPException(409, f"Conflict already resolved as {prior_decision.decision}")
    prior_decision = db.scalar(select(ReconciliationDecision).where(
        ReconciliationDecision.workspace_id == workspace.id,
        ReconciliationDecision.conflict_event_id == event_id,
    ))
    if prior_decision:
        return replay_or_reject(prior_decision)
    incoming = db.scalar(select(BusinessEvent).where(BusinessEvent.id == event_id,
        BusinessEvent.workspace_id == workspace.id).with_for_update())
    prior_decision = db.scalar(select(ReconciliationDecision).where(
        ReconciliationDecision.workspace_id == workspace.id,
        ReconciliationDecision.conflict_event_id == event_id,
    ))
    if prior_decision:
        return replay_or_reject(prior_decision)
    if incoming is None or incoming.reconciliation_status != "conflict" or not incoming.matched_event_id:
        raise HTTPException(404, "Unresolved conflict not found")
    candidates_query = select(BusinessEvent).where(
        BusinessEvent.workspace_id == workspace.id,
        BusinessEvent.event_type == incoming.event_type,
        BusinessEvent.reconciliation_status == "accepted",
        BusinessEvent.is_current.is_(True),
    )
    if incoming.entity_id:
        candidates_query = candidates_query.where(BusinessEvent.entity_id == incoming.entity_id)
    else:
        candidates_query = candidates_query.where(BusinessEvent.id == incoming.matched_event_id)
    candidates = db.scalars(candidates_query.order_by(desc(BusinessEvent.created_at), desc(BusinessEvent.id))
                            .with_for_update()).all()
    if not candidates:
        raise HTTPException(409, "The matched record is stale or deleted; refresh the source before resolving")
    existing = candidates[0]
    if payload.decision == "accept_incoming":
        for candidate in candidates:
            candidate.is_current = False
        db.flush()
        incoming.is_current = True
        incoming.current_key = (f"{incoming.event_type}:{incoming.entity_id}" if incoming.event_type in
                                {"order", "fulfillment", "cancellation", "appointment_outcome"}
                                and incoming.entity_id else
                                f"{incoming.event_type}:{incoming.source_id}:{incoming.source_event_id}")
        incoming.reconciliation_status = "accepted"
        incoming.reconciliation_note = "owner_reviewed_accept_incoming"
        incoming.matched_event_id = existing.id
        incoming.supersedes_event_id = existing.id
        selected = incoming
    elif payload.decision == "retain_existing":
        incoming.is_current = False
        incoming.reconciliation_status = "rejected"
        incoming.reconciliation_note = "owner_reviewed_retain_existing"
        incoming.matched_event_id = existing.id
        selected = existing
    else:
        incoming.is_current = False
        incoming.reconciliation_status = "duplicate"
        incoming.reconciliation_note = "owner_reviewed_mark_duplicate"
        incoming.matched_event_id = existing.id
        selected = existing
    decision = ReconciliationDecision(workspace_id=workspace.id, conflict_event_id=incoming.id,
        selected_event_id=selected.id, decided_by_user_id=user.id, decision=payload.decision,
        note=payload.note, provenance={"incoming": incoming.provenance, "existing": existing.provenance})
    db.add(decision)
    context = type("WorkspaceContext", (), {"workspace_id": workspace.id})()
    record_audit(db, context, user.id, "data_conflict.resolved", "business_event", incoming.id,
                 {"decision": payload.decision, "selected_event_id": selected.id,
                  "decision_id": decision.id, "note": payload.note})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior_decision = db.scalar(select(ReconciliationDecision).where(
            ReconciliationDecision.workspace_id == workspace.id,
            ReconciliationDecision.conflict_event_id == event_id,
        ))
        if prior_decision:
            return replay_or_reject(prior_decision)
        raise HTTPException(409, "Conflict was resolved concurrently; refresh the data quality page") from None
    return {"decision_id": decision.id, "conflict_event_id": incoming.id,
            "selected_event_id": selected.id, "decision": payload.decision, "replayed": False}
