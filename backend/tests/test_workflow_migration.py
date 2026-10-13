"""Run migration 0009 against SQLite and an optional isolated PostgreSQL schema."""
import importlib.util
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models import Membership, User, Workspace


def test_0009_persists_jobs_checkpoints_and_writes_with_tenant_keys():
    engine = sa.create_engine(os.getenv("TEST_MIGRATION_DATABASE_URL", os.getenv("TEST_DATABASE_URL", "sqlite://")))
    schema = f"test_workflow_migration_{uuid.uuid4().hex}"
    postgres = engine.dialect.name == "postgresql"
    module_path = Path(__file__).parents[1] / "migrations/versions/0009_durable_workflows.py"
    spec = importlib.util.spec_from_file_location("workflow_migration", module_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    prior_investigations = sa.Table(
        "investigation_runs", MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(100)), sa.Column("prompt_version", sa.String(30), nullable=False),
        sa.Column("input_tokens", sa.Integer()), sa.Column("output_tokens", sa.Integer()),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 8)), sa.Column("cost_schedule", sa.String(40)),
        sa.Column("confidence", sa.Numeric(4, 3)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    try:
        with engine.begin() as connection:
            if postgres:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            else:
                connection.execute(text("PRAGMA foreign_keys=ON"))
            Base.metadata.create_all(connection, tables=[User.__table__, Workspace.__table__, Membership.__table__])
            prior_investigations.create(connection)
            now = datetime.now(timezone.utc)
            connection.execute(User.__table__.insert(), {"id": "user-1", "email": "worker@example.com",
                                                          "password_hash": "test"})
            connection.execute(Workspace.__table__.insert(), {"id": "workspace-1", "name": "Private store",
                                                               "industry": "ecommerce"})
            connection.execute(prior_investigations.insert(), {"id": "run-1", "workspace_id": "workspace-1",
                "question": "Prior review", "status": "evidence_ready", "result": {"findings": []},
                "prompt_version": "evidence-v1", "created_at": now})
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                tables = {name: sa.Table(name, MetaData(), autoload_with=connection) for name in (
                    "workflow_jobs", "workflow_checkpoints", "workflow_checkpoint_writes")}
                assert "job_id" in {column["name"] for column in inspect(connection).get_columns("investigation_runs")}
                job = {"id": "job-1", "workspace_id": "workspace-1", "requested_by_user_id": "user-1",
                       "kind": "investigation", "status": "queued", "idempotency_key": "user-1:request-1",
                       "payload": {"question": "Why?"}, "result": None, "error_code": None, "attempts": 0,
                       "cancel_requested": False, "lease_token": None, "lease_expires_at": None,
                       "current_step": None, "created_at": now, "updated_at": now,
                       "started_at": None, "finished_at": None}
                connection.execute(tables["workflow_jobs"].insert(), job)
                checkpoint = {"id": "cp-1", "workspace_id": "workspace-1", "job_id": "job-1",
                              "thread_id": "job-1", "checkpoint_ns": "", "checkpoint_id": "cp-1",
                              "parent_checkpoint_id": None, "checkpoint": {"next": []},
                              "metadata": {"source": "loop"}, "created_at": now}
                connection.execute(tables["workflow_checkpoints"].insert(), checkpoint)
                write = {"id": "write-1", "workspace_id": "workspace-1", "job_id": "job-1",
                         "thread_id": "job-1", "checkpoint_ns": "", "checkpoint_id": "cp-1",
                         "task_id": "task-1", "task_path": "", "write_index": 0,
                         "channel": "output", "value": {"value": "safe-json"}}
                connection.execute(tables["workflow_checkpoint_writes"].insert(), write)
                assert connection.execute(select(tables["workflow_checkpoint_writes"])).one().value == {
                    "value": "safe-json"}
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(tables["workflow_jobs"].insert(), {**job, "id": "job-2"})
                migration.downgrade()
                assert not set(tables) & set(inspect(connection).get_table_names())
                assert "job_id" not in {column["name"] for column in inspect(connection).get_columns("investigation_runs")}
                assert connection.execute(select(prior_investigations)).one().result == {"findings": []}
    finally:
        if postgres:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
