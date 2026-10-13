"""One-off release job: migrate with admin credentials, provision runtime roles.

Run only in the migration service, never in an API/worker startup command.
"""
import logging
import os
import time

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.deployment import configure_logging

logger = logging.getLogger("marketmind.migrations")
LOCK_ID = 730145817


def provision_roles(connection, passwords: dict[str, str]) -> None:
    """Administrator owns schema; runtime logins cannot bypass RLS or run DDL."""
    with connection.connection.driver_connection.cursor() as cursor:
        for role, password in passwords.items():
            if len(password) < 32 or password.startswith("REPLACE_"):
                raise ValueError("Provide distinct random database passwords of at least 32 characters")
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (role,))
            exists = cursor.fetchone()[0]
            if exists:
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r "
                               "ON r.oid = m.member WHERE r.rolname = %s)", (role,))
                if cursor.fetchone()[0]:
                    raise ValueError("Runtime roles must not inherit other database roles")
            cursor.execute(sql.SQL("{} ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                                   "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}").format(
                sql.SQL("ALTER" if exists else "CREATE"), sql.Identifier(role), sql.Literal(password)))
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        for role in passwords:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(role)))
        cursor.execute("GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO marketmind_api")
        cursor.execute("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM marketmind_api")
        # Workers read source evidence and write only queue/AI output tables.
        outputs = ("investigation_runs", "audit_events", "growth_strategy_runs", "growth_recommendations",
                   "experiment_evaluations", "experiment_learnings", "workflow_checkpoints",
                   "workflow_checkpoint_writes")
        for table in outputs:
            cursor.execute(sql.SQL("GRANT INSERT, UPDATE, DELETE ON {} TO marketmind_worker").format(
                sql.Identifier(table)))
        cursor.execute("GRANT UPDATE (status, attempts, lease_token, lease_expires_at, current_step, "
                       "started_at, updated_at, finished_at, result, error_code) "
                       "ON workflow_jobs TO marketmind_worker")


def migrate() -> None:
    url = Settings.normalize_database_url(os.environ["MIGRATION_DATABASE_URL"])
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("Release migrations require PostgreSQL")
    passwords = {"marketmind_api": os.environ["API_DATABASE_PASSWORD"],
                 "marketmind_worker": os.environ["WORKER_DATABASE_PASSWORD"]}
    if passwords["marketmind_api"] == passwords["marketmind_worker"]:
        raise ValueError("Runtime services require different database passwords")
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            deadline = time.monotonic() + 60
            while not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}):
                connection.rollback()
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another migration job holds the release lock")
                time.sleep(1)
            connection.commit()
            try:
                config = Config("alembic.ini")
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                connection.commit()
                with connection.begin():
                    provision_roles(connection, passwords)
                logger.info("migration_completed revision=head runtime_roles=restricted")
            finally:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
                connection.commit()
    finally:
        engine.dispose()


def main() -> None:
    configure_logging()
    try:
        migrate()
    except Exception as error:
        logger.error("migration_failed error_type=%s; check database availability, pgvector and migration credentials",
                     type(error).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
