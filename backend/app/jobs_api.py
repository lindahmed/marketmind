"""Authenticated enqueue/status/cancel APIs for durable tenant workflows."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api import require_context
from app.auth import CurrentUser, Db, Tenant
from app.growth_api import assert_fresh_evidence, investigation_for
from app.models import Membership, WorkflowJob
from app.workflow_jobs import WorkflowJobError, enqueue_job, job_view

router = APIRouter(prefix="/api/workflow-jobs")


class WorkflowJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["investigation", "growth_strategy"]
    payload: dict[str, str]
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")

    @model_validator(mode="after")
    def validate_payload(self):
        if self.kind == "investigation":
            if set(self.payload) != {"question"} or not 1 <= len(self.payload["question"].strip()) <= 1000:
                raise ValueError("Investigation jobs require one question of 1–1000 characters")
        elif self.kind == "growth_strategy":
            if set(self.payload) != {"investigation_id"} or not self.payload["investigation_id"]:
                raise ValueError("Growth strategy jobs require one investigation ID")
        return self


@router.post("", status_code=202)
def create_job(payload: WorkflowJobRequest, workspace: Tenant, db: Db, user: CurrentUser):
    context = require_context(db, user, workspace)
    if payload.kind == "growth_strategy":
        investigation = investigation_for(db, context, payload.payload["investigation_id"])
        assert_fresh_evidence(db, workspace, context, investigation)
    try:
        row, duplicate = enqueue_job(
            db, workspace_id=workspace.id, requested_by_user_id=user.id, kind=payload.kind,
            payload=payload.payload, idempotency_key=f"{user.id}:{payload.idempotency_key}",
        )
        db.commit()
        db.refresh(row)
    except WorkflowJobError as error:
        db.rollback()
        raise HTTPException(409, "Idempotency key was already used for a different job request") from error
    return {**job_view(row), "duplicate": duplicate}


@router.get("")
def list_jobs(workspace: Tenant, db: Db, user: CurrentUser):
    require_context(db, user, workspace)
    rows = db.scalars(select(WorkflowJob).where(
        WorkflowJob.workspace_id == workspace.id,
    ).order_by(WorkflowJob.created_at.desc(), WorkflowJob.id).limit(50)).all()
    return [job_view(row) for row in rows]


@router.get("/{job_id}")
def get_job(job_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    require_context(db, user, workspace)
    row = db.scalar(select(WorkflowJob).where(
        WorkflowJob.id == job_id, WorkflowJob.workspace_id == workspace.id,
    ))
    if row is None:
        raise HTTPException(404, "Workflow job not found")
    return job_view(row)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, workspace: Tenant, db: Db, user: CurrentUser):
    require_context(db, user, workspace)
    row = db.scalar(select(WorkflowJob).where(
        WorkflowJob.id == job_id, WorkflowJob.workspace_id == workspace.id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "Workflow job not found")
    member = db.scalar(select(Membership).where(
        Membership.user_id == user.id, Membership.workspace_id == workspace.id,
    ))
    if row.requested_by_user_id != user.id and (member is None or member.role != "owner"):
        raise HTTPException(403, "Only the job requester or workspace owner can cancel this job")
    if row.status == "queued":
        row.status = "cancelled"
        row.finished_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
    elif row.status == "running":
        row.cancel_requested = True
        row.updated_at = datetime.now(timezone.utc)
    else:
        raise HTTPException(409, "This workflow job is already terminal")
    db.commit()
    db.refresh(row)
    return job_view(row)
