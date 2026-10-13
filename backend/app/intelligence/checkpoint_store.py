"""Tenant-checked SQL checkpoint storage for the JSON-only workflow job graphs."""
from datetime import datetime, timezone
from typing import Any, Iterator

from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata, CheckpointTuple
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import WorkflowCheckpoint, WorkflowCheckpointWrite, WorkflowJob
from app.db import set_db_scope
from app.job_lease import fence_session


def _scope(config: dict | None) -> tuple[str, str, str] | None:
    configurable = (config or {}).get("configurable", {})
    workspace_id = configurable.get("workspace_id")
    thread_id = configurable.get("thread_id")
    namespace = configurable.get("checkpoint_ns", "")
    if not workspace_id or not thread_id:
        return None
    return workspace_id, thread_id, namespace


class TenantCheckpointSaver(BaseCheckpointSaver):
    """Persist only JSON-compatible graph state, isolated by workspace and job.

    The task graph deliberately carries identifiers and JSON values only. ORM
    instances, credentials, and agent clients never enter checkpoint storage.
    """

    def __init__(self, session_factory: sessionmaker):
        super().__init__()
        self.session_factory = session_factory

    def _valid_job(self, session, workspace_id: str, thread_id: str) -> bool:
        set_db_scope(session, workspace_id=workspace_id)
        job = session.scalar(select(WorkflowJob.id).where(
            WorkflowJob.id == thread_id, WorkflowJob.workspace_id == workspace_id,
        ))
        return job is not None

    def put(self, config: dict, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: dict) -> dict:
        scope = _scope(config)
        if scope is None:
            raise ValueError("A tenant and job ID are required for checkpoint writes")
        workspace_id, thread_id, namespace = scope
        checkpoint_id = checkpoint["id"]
        parent_id = config.get("configurable", {}).get("checkpoint_id")
        with self.session_factory.begin() as session:
            fence_session(session, workspace_id, thread_id, config.get("configurable", {}).get("lease_token"))
            if not self._valid_job(session, workspace_id, thread_id):
                raise PermissionError("Checkpoint job does not belong to this workspace")
            row = session.scalar(select(WorkflowCheckpoint).where(
                WorkflowCheckpoint.workspace_id == workspace_id,
                WorkflowCheckpoint.thread_id == thread_id,
                WorkflowCheckpoint.checkpoint_ns == namespace,
                WorkflowCheckpoint.checkpoint_id == checkpoint_id,
            ))
            values = {"checkpoint": checkpoint, "metadata_json": metadata,
                      "parent_checkpoint_id": parent_id,
                      "created_at": datetime.now(timezone.utc)}
            if row is None:
                session.add(WorkflowCheckpoint(workspace_id=workspace_id, job_id=thread_id,
                                               thread_id=thread_id, checkpoint_ns=namespace,
                                               checkpoint_id=checkpoint_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return {"configurable": {**config.get("configurable", {}), "checkpoint_id": checkpoint_id}}

    def put_writes(self, config: dict, writes, task_id: str, task_path: str = "") -> None:
        scope = _scope(config)
        if scope is None:
            raise ValueError("A tenant and job ID are required for checkpoint writes")
        workspace_id, thread_id, namespace = scope
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if not checkpoint_id:
            raise ValueError("Checkpoint ID is required for pending writes")
        with self.session_factory.begin() as session:
            fence_session(session, workspace_id, thread_id, config.get("configurable", {}).get("lease_token"))
            if not self._valid_job(session, workspace_id, thread_id):
                raise PermissionError("Checkpoint does not belong to this workspace")
            for index, (channel, value) in enumerate(writes):
                row = session.scalar(select(WorkflowCheckpointWrite).where(
                    WorkflowCheckpointWrite.workspace_id == workspace_id,
                    WorkflowCheckpointWrite.thread_id == thread_id,
                    WorkflowCheckpointWrite.checkpoint_ns == namespace,
                    WorkflowCheckpointWrite.checkpoint_id == checkpoint_id,
                    WorkflowCheckpointWrite.task_id == task_id,
                    WorkflowCheckpointWrite.write_index == index,
                ))
                if row is None:
                    session.add(WorkflowCheckpointWrite(
                        workspace_id=workspace_id, job_id=thread_id, thread_id=thread_id,
                        checkpoint_ns=namespace, checkpoint_id=checkpoint_id, task_id=task_id,
                        task_path=task_path, write_index=index, channel=channel, value=value,
                    ))
                else:
                    row.task_path = task_path
                    row.channel = channel
                    row.value = value

    def get_tuple(self, config: dict) -> CheckpointTuple | None:
        scope = _scope(config)
        if scope is None:
            return None
        workspace_id, thread_id, namespace = scope
        configurable = config["configurable"]
        with self.session_factory() as session:
            if not self._valid_job(session, workspace_id, thread_id):
                return None
            query = select(WorkflowCheckpoint).where(
                WorkflowCheckpoint.workspace_id == workspace_id,
                WorkflowCheckpoint.job_id == thread_id,
                WorkflowCheckpoint.thread_id == thread_id,
                WorkflowCheckpoint.checkpoint_ns == namespace,
            )
            checkpoint_id = configurable.get("checkpoint_id")
            if checkpoint_id:
                query = query.where(WorkflowCheckpoint.checkpoint_id == checkpoint_id)
            row = session.scalar(query.order_by(WorkflowCheckpoint.created_at.desc()).limit(1))
            if row is None:
                return None
            saved_config = {"configurable": {"workspace_id": workspace_id, "thread_id": thread_id,
                                              "checkpoint_ns": namespace, "checkpoint_id": row.checkpoint_id}}
            parent = ({"configurable": {"workspace_id": workspace_id, "thread_id": thread_id,
                                         "checkpoint_ns": namespace, "checkpoint_id": row.parent_checkpoint_id}}
                      if row.parent_checkpoint_id else None)
            writes = session.scalars(select(WorkflowCheckpointWrite).where(
                WorkflowCheckpointWrite.workspace_id == workspace_id,
                WorkflowCheckpointWrite.thread_id == thread_id,
                WorkflowCheckpointWrite.checkpoint_ns == namespace,
                WorkflowCheckpointWrite.checkpoint_id == row.checkpoint_id,
            ).order_by(WorkflowCheckpointWrite.task_id, WorkflowCheckpointWrite.write_index)).all()
            pending = [(write.task_id, write.channel, write.value) for write in writes]
            return CheckpointTuple(saved_config, row.checkpoint, row.metadata_json or {}, parent, pending)

    def list(self, config: dict | None, *, filter: dict[str, Any] | None = None,
             before: dict | None = None, limit: int | None = None) -> Iterator[CheckpointTuple]:
        scope = _scope(config)
        if scope is None:
            return iter(())
        workspace_id, thread_id, namespace = scope
        with self.session_factory() as session:
            if not self._valid_job(session, workspace_id, thread_id):
                return iter(())
            rows = session.scalars(select(WorkflowCheckpoint).where(
                WorkflowCheckpoint.workspace_id == workspace_id,
                WorkflowCheckpoint.job_id == thread_id,
                WorkflowCheckpoint.thread_id == thread_id,
                WorkflowCheckpoint.checkpoint_ns == namespace,
            ).order_by(WorkflowCheckpoint.created_at.desc())).all()
            tuples = []
            before_id = ((before or {}).get("configurable", {}).get("checkpoint_id"))
            boundary = next((row.created_at for row in rows if row.checkpoint_id == before_id), None)
            for row in rows:
                if boundary and row.created_at >= boundary:
                    continue
                if filter and any((row.metadata_json or {}).get(key) != value for key, value in filter.items()):
                    continue
                saved_config = {"configurable": {"workspace_id": workspace_id, "thread_id": thread_id,
                                                  "checkpoint_ns": namespace, "checkpoint_id": row.checkpoint_id}}
                parent = ({"configurable": {"workspace_id": workspace_id, "thread_id": thread_id,
                                             "checkpoint_ns": namespace, "checkpoint_id": row.parent_checkpoint_id}}
                          if row.parent_checkpoint_id else None)
                writes = session.scalars(select(WorkflowCheckpointWrite).where(
                    WorkflowCheckpointWrite.workspace_id == workspace_id,
                    WorkflowCheckpointWrite.thread_id == thread_id,
                    WorkflowCheckpointWrite.checkpoint_ns == namespace,
                    WorkflowCheckpointWrite.checkpoint_id == row.checkpoint_id,
                ).order_by(WorkflowCheckpointWrite.task_id, WorkflowCheckpointWrite.write_index)).all()
                pending = [(write.task_id, write.channel, write.value) for write in writes]
                tuples.append(CheckpointTuple(saved_config, row.checkpoint, row.metadata_json or {}, parent, pending))
                if limit and len(tuples) >= limit:
                    break
            return iter(tuples)

    def delete_thread(self, thread_id: str) -> None:
        # LangGraph's generic API supplies no workspace or authorization here.
        # Deleting checkpoints by an unscoped caller is deliberately forbidden.
        raise PermissionError("Workspace-scoped checkpoint deletion is required")
