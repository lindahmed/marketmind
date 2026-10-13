"""Append-only reconciliation for imported source events."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BusinessEvent, DataCoverage, DataImportRun, DataSource
from app.schemas import BusinessEventInput, DataSourceBatch

REQUIRED = {
    "order": ("entity_id", "amount", "currency"),
    "fulfillment": ("entity_id", "status"),
    "cancellation": ("entity_id",),
    "refund": ("entity_id", "amount", "currency"),
    "payment": ("entity_id", "amount", "currency", "status"),
    "marketing_spend": ("entity_id", "amount", "currency"),
    "appointment_outcome": ("entity_id", "status"),
    "expense": ("entity_id", "amount", "currency", "cost_category"),
}


def event_payload(event: BusinessEventInput) -> dict:
    payload = event.model_dump(mode="json", exclude={"record_locator", "source_event_id"})
    happened = event.occurred_at
    if happened.tzinfo is None:
        happened = happened.replace(tzinfo=timezone.utc)
    payload["occurred_at"] = happened.astimezone(timezone.utc).isoformat()
    for field in ("booked_at", "scheduled_at", "completed_at"):
        value = getattr(event, field)
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            payload[field] = value.astimezone(timezone.utc).isoformat()
    return payload


def event_fingerprint(event: BusinessEventInput) -> str:
    canonical = event_payload(event)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def missing_fields(event: BusinessEventInput, industry: str | None = None) -> list[str]:
    value = event.model_dump()
    missing = [field for field in REQUIRED[event.event_type] if value[field] is None or value[field] == ""]
    if industry == "ecommerce" and event.event_type == "appointment_outcome":
        missing.append("event_type_not_supported_for_ecommerce")
    if industry == "appointments" and event.event_type in {"order", "fulfillment", "cancellation"}:
        missing.append("event_type_not_supported_for_appointments")
    if event.event_type == "fulfillment" and event.status not in {"fulfilled", "delayed", "pending"}:
        missing.append("status:expected_fulfilled_delayed_or_pending")
    if event.event_type == "appointment_outcome" and event.status not in {"booked", "completed", "cancelled", "no_show"}:
        missing.append("status:expected_booked_completed_cancelled_or_no_show")
    if event.event_type == "payment" and event.status not in {"captured", "pending", "failed", "refunded"}:
        missing.append("status:expected_captured_pending_failed_or_refunded")
    return missing


def record_batch(db: Session, source: DataSource, batch: DataSourceBatch,
                 industry: str | None = None) -> tuple[DataImportRun, bool]:
    payload = batch.model_dump(mode="json")
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing_run = db.scalar(select(DataImportRun).where(
        DataImportRun.source_id == source.id, DataImportRun.request_id == batch.request_id,
    ))
    if existing_run:
        if existing_run.payload_hash != payload_hash:
            raise ValueError("request_id was already used with a different payload")
        return existing_run, True

    now = datetime.now(timezone.utc)
    run = DataImportRun(workspace_id=source.workspace_id, source_id=source.id, request_id=batch.request_id,
                        payload_hash=payload_hash, received_count=len(batch.records), started_at=now)
    db.add(run)
    db.flush()
    for event in batch.records:
        value = event.model_dump()
        occurred_at = value["occurred_at"]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        occurred_at = occurred_at.astimezone(timezone.utc)
        appointment_dates = {}
        for field in ("booked_at", "scheduled_at", "completed_at"):
            appointment_date = value[field]
            if appointment_date is not None:
                if appointment_date.tzinfo is None:
                    appointment_date = appointment_date.replace(tzinfo=timezone.utc)
                appointment_dates[field] = appointment_date.astimezone(timezone.utc)
        digest = event_fingerprint(event)
        required_missing = missing_fields(event, industry)
        match = None
        if not required_missing:
            # Stable source row ID handles corrections. Entity ID handles lifecycle snapshots;
            # payment/refund rows are transaction-level and may legitimately share an order ID.
            match = db.scalar(select(BusinessEvent).where(
                BusinessEvent.workspace_id == source.workspace_id,
                BusinessEvent.source_id == source.id,
                BusinessEvent.event_type == event.event_type,
                BusinessEvent.source_event_id == event.source_event_id,
            ).order_by(BusinessEvent.is_current.desc(), BusinessEvent.created_at.desc(),
                       BusinessEvent.id.desc()).limit(1))
            lifecycle = {"order", "fulfillment", "cancellation", "appointment_outcome"}
            if match is None and event.event_type in lifecycle and event.entity_id:
                match = db.scalar(select(BusinessEvent).where(
                    BusinessEvent.workspace_id == source.workspace_id,
                    BusinessEvent.source_id == source.id,
                    BusinessEvent.event_type == event.event_type,
                    BusinessEvent.entity_id == event.entity_id,
                    BusinessEvent.is_current.is_(True),
                    BusinessEvent.reconciliation_status == "accepted",
                ).order_by(BusinessEvent.created_at.desc(), BusinessEvent.id.desc()).limit(1))
            if match is None and event.entity_id:
                match = db.scalar(select(BusinessEvent).where(
                    BusinessEvent.workspace_id == source.workspace_id,
                    BusinessEvent.event_type == event.event_type,
                    BusinessEvent.entity_id == event.entity_id,
                    BusinessEvent.is_current.is_(True),
                    BusinessEvent.reconciliation_status == "accepted",
                ).order_by(BusinessEvent.created_at, BusinessEvent.id).limit(1))

        if required_missing:
            status, note = "missing", "missing_required_fields:" + ",".join(required_missing)
            matched_id = None
            run.missing_count += 1
        elif match is None:
            status, note, matched_id = "accepted", None, None
            run.accepted_count += 1
        elif match.record_hash == digest:
            status, note, matched_id = "duplicate", "identical_record_from_existing_source", match.id
            run.duplicate_count += 1
        elif match.source_id == source.id:
            status, note, matched_id = "accepted", "corrected_source_record_supersedes_prior_version", match.id
            match.is_current = False
            run.accepted_count += 1
        else:
            status, note, matched_id = "conflict", "record_differs_from_existing_source_record", match.id
            run.conflict_count += 1

        current = status == "accepted"
        # For same-source lifecycle rows with a changed source row ID, preserve only the newest
        # state in analytics. Each version remains in the event ledger.
        lifecycle = {"order", "fulfillment", "cancellation", "appointment_outcome"}
        if current and event.event_type in lifecycle and event.entity_id:
            prior_rows = db.scalars(select(BusinessEvent).where(
                BusinessEvent.workspace_id == source.workspace_id,
                BusinessEvent.source_id == source.id,
                BusinessEvent.event_type == event.event_type,
                BusinessEvent.entity_id == event.entity_id,
                BusinessEvent.is_current.is_(True),
                BusinessEvent.reconciliation_status == "accepted",
            )).all()
            for prior in prior_rows:
                prior.is_current = False
        if current:
            if event.event_type in lifecycle and event.entity_id:
                current_key = f"{event.event_type}:{event.entity_id}"
            else:
                current_key = f"{event.event_type}:{source.id}:{event.source_event_id}"
        else:
            current_key = None
        db.add(BusinessEvent(
            workspace_id=source.workspace_id, source_id=source.id, import_run_id=run.id,
            source_event_id=event.source_event_id, event_type=event.event_type, entity_id=event.entity_id,
            occurred_at=occurred_at, **appointment_dates, amount=event.amount, currency=event.currency,
            status_value=event.status,
            quantity=event.quantity, cost_category=event.cost_category, campaign_id=event.campaign_id,
            channel=event.channel,
            provenance={"provider": source.provider, "source_identifier": source.source_identifier,
                        "request_id": batch.request_id, "record_locator": event.record_locator},
            record_hash=digest, reconciliation_status=status, reconciliation_note=note, matched_event_id=matched_id,
            is_current=current, supersedes_event_id=(match.id if match and source.id == match.source_id else None),
            current_key=current_key,
        ))
    if batch.deleted_source_event_ids:
        deleted = db.scalars(select(BusinessEvent).where(
            BusinessEvent.workspace_id == source.workspace_id, BusinessEvent.source_id == source.id,
            BusinessEvent.source_event_id.in_(batch.deleted_source_event_ids),
            BusinessEvent.is_current.is_(True),
        )).all()
        for event in deleted:
            event.is_current = False
            db.add(BusinessEvent(
                workspace_id=event.workspace_id, source_id=event.source_id, import_run_id=run.id,
                source_event_id=event.source_event_id, event_type=event.event_type, entity_id=event.entity_id,
                occurred_at=event.occurred_at, booked_at=event.booked_at, scheduled_at=event.scheduled_at,
                completed_at=event.completed_at, amount=event.amount, currency=event.currency,
                status_value=event.status_value, quantity=event.quantity, cost_category=event.cost_category,
                campaign_id=event.campaign_id, channel=event.channel,
                provenance={"action": "source_record_deleted", "request_id": batch.request_id,
                            "deleted_provenance": event.provenance},
                record_hash=event.record_hash, reconciliation_status="deleted",
                reconciliation_note="source_record_deleted; historical_version_retained",
                matched_event_id=event.id, is_current=False,
            ))
            run.deleted_count += 1
    for item in batch.coverage:
        existing = db.scalar(select(DataCoverage).where(
            DataCoverage.workspace_id == source.workspace_id, DataCoverage.source_id == source.id,
            DataCoverage.day == item.day, DataCoverage.data_kind == item.data_kind,
            DataCoverage.is_current.is_(True),
        ))
        if existing:
            existing.is_current = False
        db.add(DataCoverage(workspace_id=source.workspace_id, source_id=source.id, import_run_id=run.id,
                            day=item.day, data_kind=item.data_kind, complete=item.complete,
                            provenance={"request_id": batch.request_id, "record_locator": item.record_locator}))
    run.status = "issues" if run.conflict_count or run.missing_count else "completed"
    run.finished_at = now
    source.last_sync_at = now
    source.sync_status = run.status
    return run, False
