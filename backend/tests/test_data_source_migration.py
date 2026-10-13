"""Exercise migration 0011 in an isolated SQLite schema."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def test_0011_creates_tenant_scoped_sources_imports_and_events():
    engine = sa.create_engine("sqlite://")
    path = Path(__file__).parents[1] / "migrations/versions/0011_trusted_data_sources.py"
    spec = importlib.util.spec_from_file_location("trusted_data_source_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            inspector = inspect(connection)
            assert {"data_sources", "data_import_runs", "business_events"}.issubset(inspector.get_table_names())
            event_columns = {column["name"] for column in inspector.get_columns("business_events")}
            assert {"workspace_id", "event_type", "amount", "campaign_id", "provenance",
                    "reconciliation_status", "matched_event_id"}.issubset(event_columns)
            source_constraints = inspector.get_unique_constraints("data_sources")
            assert any(constraint["column_names"] == ["workspace_id", "provider", "source_identifier"]
                       for constraint in source_constraints)
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert not {"data_sources", "data_import_runs", "business_events"} & set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


def test_0012_and_0013_add_current_revision_decision_coverage_and_appointment_schema():
    engine = sa.create_engine("sqlite://")
    versions = Path(__file__).parents[1] / "migrations/versions"
    migrations = []
    for filename, name in (("0011_trusted_data_sources.py", "trusted_sources"),
                           ("0012_reconciliation_state.py", "reconciliation_state"),
                           ("0013_conflict_appointment_stability.py", "conflict_appointment_stability")):
        spec = importlib.util.spec_from_file_location(name, versions / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        migrations.append(module)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
            with Operations.context(MigrationContext.configure(connection)):
                migrations[0].upgrade()
                migrations[1].upgrade()
                migrations[2].upgrade()
            inspector = inspect(connection)
            assert {"reconciliation_decisions", "data_coverage"}.issubset(inspector.get_table_names())
            columns = {item["name"] for item in inspector.get_columns("business_events")}
            assert {"is_current", "supersedes_event_id", "current_key"}.issubset(columns)
            assert {"booked_at", "scheduled_at", "completed_at"}.issubset(columns)
            run_columns = {item["name"] for item in inspector.get_columns("data_import_runs")}
            assert "deleted_count" in run_columns
            indexes = inspector.get_indexes("business_events")
            assert any(index["name"] == "uq_business_events_current_key" and index["unique"] for index in indexes)
            coverage_indexes = inspector.get_indexes("data_coverage")
            assert any(index["name"] == "uq_data_coverage_current_source_day_kind" and index["unique"]
                       for index in coverage_indexes)
            decision_indexes = inspector.get_indexes("reconciliation_decisions")
            assert any(index["name"] == "uq_reconciliation_decision_conflict" and index["unique"]
                       for index in decision_indexes)
            with Operations.context(MigrationContext.configure(connection)):
                migrations[2].downgrade()
                migrations[1].downgrade()
                migrations[0].downgrade()
    finally:
        engine.dispose()
