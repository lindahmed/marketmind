"""Renew leases and fence domain writes with the same locked queue row."""
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import set_db_scope
from app.models import WorkflowJob

logger = logging.getLogger("marketmind.worker")


class LeaseLost(Exception):
    pass


def fence_session(session, workspace_id: str, job_id: str, token: str | None) -> None:
    set_db_scope(session, workspace_id=workspace_id)
    if token:
        session.info["workflow_lease"] = (workspace_id, job_id, token)
    elif get_settings().environment == "production":
        raise LeaseLost("A running worker lease is required")


def _fence(session: Session) -> None:
    scope = session.info.get("workflow_lease")
    if not scope:
        return
    workspace_id, job_id, token = scope
    # Keep the row locked until domain writes commit. Recovery, cancellation
    # and a competing worker cannot change ownership between this check and commit.
    row = session.execute(select(WorkflowJob.status, WorkflowJob.lease_token,
                                 WorkflowJob.lease_expires_at, WorkflowJob.cancel_requested).where(
        WorkflowJob.id == job_id, WorkflowJob.workspace_id == workspace_id,
    ).with_for_update()).first()
    expiry = row[2] if row else None
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if (row is None or row[0] != "running" or row[1] != token or not expiry
            or expiry <= datetime.now(timezone.utc) or row[3]):
        raise LeaseLost("Worker lease expired, changed or cancelled")


@event.listens_for(Session, "before_flush")
def fence_flush(session, flush_context, instances):
    _fence(session)


@event.listens_for(Session, "before_commit")
def fence_commit(session):
    _fence(session)


def renew_lease(factory, workspace_id: str, job_id: str, token: str) -> bool:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    with factory.begin() as session:
        set_db_scope(session, workspace_id=workspace_id)
        result = session.execute(update(WorkflowJob).where(
            WorkflowJob.workspace_id == workspace_id, WorkflowJob.id == job_id,
            WorkflowJob.status == "running", WorkflowJob.lease_token == token,
            WorkflowJob.lease_expires_at > now,
        ).values(lease_expires_at=now + timedelta(seconds=settings.worker_lease_seconds), updated_at=now))
        return result.rowcount == 1


@contextmanager
def lease_heartbeat(factory, workspace_id: str, job_id: str, token: str):
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(get_settings().worker_heartbeat_seconds):
            try:
                if not renew_lease(factory, workspace_id, job_id, token):
                    logger.warning("lease_lost workspace_id=%s job_id=%s", workspace_id, job_id)
                    return
            except Exception as error:
                logger.warning("lease_renewal_failed job_id=%s error_type=%s", job_id, type(error).__name__)
                # The write fence rejects output if renewal never recovers.

    thread = threading.Thread(target=heartbeat, name="marketmind-lease-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=12)
