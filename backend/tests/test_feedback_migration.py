"""Verify migration 0008 and uniqueness with SQLite or TEST_MIGRATION_DATABASE_URL."""
import importlib.util
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models import (Experiment, ExperimentApproval, ExperimentDesign, GrowthRecommendation,
                        GrowthStrategyRun, InvestigationRun, Membership, N8nDispatch,
                        RecommendationApproval, User, Workspace)


def test_0008_persists_callback_evaluation_and_learning_with_deduplication():
    engine = create_engine(os.getenv("TEST_MIGRATION_DATABASE_URL", os.getenv("TEST_DATABASE_URL", "sqlite://")))
    schema = f"test_feedback_migration_{uuid.uuid4().hex}"
    postgres = engine.dialect.name == "postgresql"
    spec = importlib.util.spec_from_file_location(
        "feedback_migration", Path(__file__).parents[1] / "migrations/versions/0008_experiment_feedback.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    parents = [User.__table__, Workspace.__table__, Membership.__table__, InvestigationRun.__table__,
               Experiment.__table__, ExperimentApproval.__table__, N8nDispatch.__table__,
               GrowthStrategyRun.__table__, GrowthRecommendation.__table__, RecommendationApproval.__table__,
               ExperimentDesign.__table__]
    try:
        with engine.begin() as connection:
            if postgres:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            else:
                connection.execute(text("PRAGMA foreign_keys=ON"))
            Base.metadata.create_all(connection, tables=parents)
            now = datetime.now(timezone.utc)
            connection.execute(User.__table__.insert(), {"id": "owner", "email": "owner@example.com", "password_hash": "test"})
            connection.execute(Workspace.__table__.insert(), {"id": "business", "name": "Store", "industry": "ecommerce"})
            connection.execute(Experiment.__table__.insert(), {"id": "experiment", "workspace_id": "business",
                               "created_by_user_id": "owner", "name": "Simulation", "action_type": "simulation_only",
                               "status": "approved", "version": 1, "metadata": {"scenario": "conversion_lift"},
                               "created_at": now})
            connection.execute(ExperimentApproval.__table__.insert(), {"id": "execution-approval", "workspace_id": "business",
                               "experiment_id": "experiment", "experiment_version": 1, "approved_by_user_id": "owner",
                               "status": "approved", "approved_at": now})
            connection.execute(N8nDispatch.__table__.insert(), {"id": "dispatch", "workspace_id": "business",
                               "experiment_id": "experiment", "approval_id": "execution-approval",
                               "execution_id": "execution", "idempotency_key": "business:experiment:v1",
                               "status": "acknowledged", "created_at": now})
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                metadata = MetaData()
                tables = {name: Table(name, metadata, autoload_with=connection) for name in (
                    "n8n_callback_receipts", "experiment_evaluations", "experiment_learnings")}
                receipt = {"id": "receipt", "callback_id": "execution:completed", "workspace_id": "business",
                           "experiment_id": "experiment", "dispatch_id": "dispatch",
                           "event_type": "experiment.simulation.completed", "payload_hash": "a" * 64,
                           "payload": {"mode": "simulation_only"}, "received_at": now}
                connection.execute(tables["n8n_callback_receipts"].insert(), receipt)
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(tables["n8n_callback_receipts"].insert(), {**receipt, "id": "duplicate"})
                evaluation = {"id": "evaluation", "workspace_id": "business", "experiment_id": "experiment",
                              "callback_receipt_id": "receipt", "outcome": "inconclusive",
                              "report": {"simulation_only": True}, "created_at": now}
                connection.execute(tables["experiment_evaluations"].insert(), evaluation)
                learning = {"id": "learning", "workspace_id": "business", "experiment_id": "experiment",
                            "evaluation_id": "evaluation", "content": {"limitations": ["simulated"]}, "created_at": now}
                connection.execute(tables["experiment_learnings"].insert(), learning)
                assert connection.execute(select(tables["experiment_learnings"])).one().content == {"limitations": ["simulated"]}
                assert {"ix_n8n_callback_receipts_workspace_id", "ix_experiment_evaluations_workspace_id",
                        "ix_experiment_learnings_workspace_id"} <= {
                    index["name"] for table in tables for index in inspect(connection).get_indexes(table)
                }
                migration.downgrade()
                assert not set(tables) & set(inspect(connection).get_table_names())
                assert connection.execute(select(Experiment.__table__)).one().metadata == {"scenario": "conversion_lift"}
                migration.upgrade()
    finally:
        if postgres:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
