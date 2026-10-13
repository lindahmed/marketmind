"""Verify actual migration 0007 against existing parent tables, with optional PostgreSQL."""
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
from app.models import Experiment, InvestigationRun, User, Workspace


def test_0007_persists_provenance_approval_design_and_preserves_existing_tables():
    engine = create_engine(os.getenv("TEST_MIGRATION_DATABASE_URL", os.getenv("TEST_DATABASE_URL", "sqlite://")))
    schema = f"test_growth_migration_{uuid.uuid4().hex}"
    postgres = engine.dialect.name == "postgresql"
    spec = importlib.util.spec_from_file_location(
        "growth_migration", Path(__file__).parents[1] / "migrations/versions/0007_growth_strategy.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.begin() as connection:
            if postgres:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            else:
                connection.execute(text("PRAGMA foreign_keys=ON"))
            Base.metadata.create_all(connection, tables=[User.__table__, Workspace.__table__, InvestigationRun.__table__, Experiment.__table__])
            connection.execute(User.__table__.insert(), {"id": "owner", "email": "test@example.com", "password_hash": "test-only"})
            connection.execute(Workspace.__table__.insert(), {"id": "business", "name": "A store", "industry": "ecommerce"})
            connection.execute(InvestigationRun.__table__.insert(), {"id": "investigation", "workspace_id": "business",
                                                                   "question": "Why profit?", "result": {"evidence": "real snapshot"}})
            connection.execute(Experiment.__table__.insert(), {"id": "experiment", "workspace_id": "business",
                               "created_by_user_id": "owner", "name": "Existing simulation", "action_type": "simulation_only",
                               "metadata": {"scenario": "conversion_lift"}})
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                reflected = MetaData()
                tables = {name: Table(name, reflected, autoload_with=connection) for name in (
                    "growth_strategy_runs", "growth_recommendations", "recommendation_approvals", "experiment_designs")}
                now = datetime.now(timezone.utc)
                connection.execute(tables["growth_strategy_runs"].insert(), {"id": "strategy", "workspace_id": "business",
                    "investigation_id": "investigation", "generation_key": "key", "context_snapshot": {"budget": "100.00"},
                    "source_type": "industry_rule", "prompt_version": "growth-v1", "created_at": now})
                connection.execute(tables["growth_recommendations"].insert(), {"id": "recommendation", "workspace_id": "business",
                    "strategy_run_id": "strategy", "candidate_key": "margin", "version": 1, "status": "approved",
                    "content": {"evidence_ids": ["negative_profit"]}, "created_at": now})
                approval_data = {"id": "approval", "workspace_id": "business", "recommendation_id": "recommendation",
                                 "recommendation_version": 1, "approved_by_user_id": "owner",
                                 "constraints_acknowledged": True, "approved_at": now}
                connection.execute(tables["recommendation_approvals"].insert(), approval_data)
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(tables["recommendation_approvals"].insert(), {**approval_data, "id": "duplicate"})
                design_data = {"id": "design", "workspace_id": "business", "experiment_id": "experiment",
                               "recommendation_id": "recommendation", "recommendation_approval_id": "approval",
                               "experiment_version": 1, "design": {"baseline": {"primary_value": "30.2500"}}, "created_at": now}
                connection.execute(tables["experiment_designs"].insert(), design_data)
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(tables["experiment_designs"].insert(), {**design_data, "id": "duplicate-design"})
                saved = connection.execute(select(tables["experiment_designs"])).one()
                assert saved.workspace_id == "business" and saved.recommendation_approval_id == "approval"
                assert saved.design["baseline"]["primary_value"] == "30.2500"
                approved = connection.execute(select(tables["recommendation_approvals"])).one()
                assert approved.constraints_acknowledged is True and approved.recommendation_version == 1
                assert "ix_experiment_designs_workspace_id" in {index["name"] for index in inspect(connection).get_indexes("experiment_designs")}
                migration.downgrade()
                assert not set(tables) & set(inspect(connection).get_table_names())
                assert connection.execute(select(Experiment.__table__)).one().metadata == {"scenario": "conversion_lift"}
                assert connection.execute(select(InvestigationRun.__table__)).one().result == {"evidence": "real snapshot"}
                migration.upgrade()
                assert set(tables) <= set(inspect(connection).get_table_names())
    finally:
        if postgres:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
