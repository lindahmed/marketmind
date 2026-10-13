"""Run migration 0006 against its prior daily_metrics schema, including real legacy JSON.

TEST_MIGRATION_DATABASE_URL enables PostgreSQL without requiring pgvector for this
isolated financial migration. This does not replace full-chain/vector integration tests.
"""
import importlib.util
import os
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (JSON, Column, Date, ForeignKey, MetaData, String, Table,
                        UniqueConstraint, create_engine, inspect, select, text)


def test_0006_backfills_legacy_money_counts_preserves_scope_and_round_trips():
    url = os.getenv("TEST_MIGRATION_DATABASE_URL", os.getenv("TEST_DATABASE_URL", "sqlite://"))
    engine = create_engine(url)
    schema = f"test_financial_migration_{uuid.uuid4().hex}"
    postgres = engine.dialect.name == "postgresql"
    spec = importlib.util.spec_from_file_location(
        "financial_reporting_migration", Path(__file__).parents[1] / "migrations/versions/0006_financial_reporting.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = MetaData()
    workspaces = Table("workspaces", metadata, Column("id", String(36), primary_key=True))
    daily = Table("daily_metrics", metadata, Column("id", String(36), primary_key=True),
                  Column("workspace_id", String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                  Column("day", Date, nullable=False), Column("values", JSON, nullable=False),
                  UniqueConstraint("workspace_id", "day"))
    legacy = [
        {"id": "store", "workspace_id": "tenant-a", "day": date(2026, 1, 1),
         "values": {"revenue": 100.25, "orders": 5.0, "ad_spend": 20.10, "cost_of_goods": 40.05}},
        {"id": "appointments", "workspace_id": "tenant-b", "day": date(2026, 1, 1),
         "values": {"revenue": 200.10, "bookings": 10.0, "completed": 6.0, "ad_spend": 10.05,
                    "variable_cost": 30.10}},
        {"id": "extended", "workspace_id": "tenant-a", "day": date(2026, 1, 3),
         "values": {"gross_revenue": "300.25", "refunds": "45.15", "orders": "10.0",
                    "fulfilled_orders": "7", "cancelled_orders": "2", "delayed_orders": "3",
                    "cost_of_goods": "40.05", "fulfillment_cost": "5.05", "payment_fees": "2.05",
                    "other_variable_costs": "1.05"}},
    ]
    try:
        with engine.begin() as connection:
            if postgres:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            metadata.create_all(connection)
            connection.execute(workspaces.insert(), [{"id": "tenant-a"}, {"id": "tenant-b"}])
            connection.execute(daily.insert(), legacy)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                normalized = Table("daily_metrics", MetaData(), autoload_with=connection)
                rows = {row.id: row for row in connection.execute(select(normalized))}
                assert rows["store"].gross_revenue == Decimal("100.25")
                assert rows["store"].ad_spend == Decimal("20.10")
                assert rows["store"].variable_costs == Decimal("40.05")
                assert rows["store"].orders == 5
                assert rows["appointments"].variable_costs == Decimal("30.10")
                assert rows["appointments"].completed_appointments == 6
                assert rows["appointments"].bookings == 10
                assert rows["extended"].gross_revenue == Decimal("300.25")
                assert rows["extended"].refunds == Decimal("45.15")
                assert rows["extended"].variable_costs == Decimal("48.20")
                assert rows["extended"].fulfilled_orders == 7
                assert rows["extended"].cancelled_orders == 2 and rows["extended"].delayed_orders == 3
                for old in legacy:
                    row = rows[old["id"]]
                    assert row.workspace_id == old["workspace_id"] and row.day == old["day"]
                    assert row.values == old["values"]
                    assert row.schema_version == 1
                    if old["id"] != "extended":
                        assert row.refunds == Decimal("0")
                        assert row.fulfilled_orders is None and row.cancelled_orders is None
                connection.execute(daily.insert(), {"id": "defaults", "workspace_id": "tenant-a",
                                                     "day": date(2026, 1, 2), "values": {}})
                defaults = connection.execute(select(normalized).where(normalized.c.id == "defaults")).one()
                assert defaults.schema_version == 1 and defaults.gross_revenue == Decimal("0")
                assert defaults.variable_costs == Decimal("0") and defaults.fulfilled_orders is None
                migration.downgrade()
                assert {column["name"] for column in inspect(connection).get_columns("daily_metrics")} == {
                    "id", "workspace_id", "day", "values",
                }
                assert connection.execute(select(daily).where(daily.c.id == "store")).one().values == legacy[0]["values"]
                migration.upgrade()
                assert connection.execute(select(normalized).where(normalized.c.id == "store")).one().orders == 5
    finally:
        if postgres:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
