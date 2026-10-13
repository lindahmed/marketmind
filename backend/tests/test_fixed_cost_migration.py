"""Regression test for the additive fixed-cost migration."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def test_0010_adds_and_removes_fixed_costs_on_sqlite():
    engine = sa.create_engine("sqlite://")
    path = Path(__file__).parents[1] / "migrations/versions/0010_fixed_cost_reporting.py"
    spec = importlib.util.spec_from_file_location("fixed_cost_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE daily_metrics (id VARCHAR(36) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO daily_metrics (id) VALUES ('legacy-row')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            columns = {column["name"]: column for column in inspect(connection).get_columns("daily_metrics")}
            assert columns["fixed_costs"]["nullable"] is False
            assert connection.execute(text("SELECT fixed_costs FROM daily_metrics WHERE id='legacy-row'")).scalar_one() == 0
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert "fixed_costs" not in {column["name"] for column in inspect(connection).get_columns("daily_metrics")}
    finally:
        engine.dispose()
