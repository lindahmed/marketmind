"""Startup gates. Errors deliberately exclude credentials, SQL and tenant data."""
import logging

from sqlalchemy import text

logger = logging.getLogger("marketmind.deployment")
EXPECTED_REVISION = "0015"


def check_database(engine, service_role: str, *, production: bool) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if not production:
            return
        role = connection.execute(text(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )).one()
        if role[0] != f"marketmind_{service_role}" or role[1] or role[2]:
            raise RuntimeError("Use the restricted database login for this service")
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != EXPECTED_REVISION:
            raise RuntimeError("Run the migration job for this release before starting services")
        if not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")):
            raise RuntimeError("The database must have pgvector installed")
        protected = connection.execute(text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   pg_get_userbyid(c.relowner) = current_user AS owned
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND c.relkind = 'r'
              AND (c.relname = 'workspaces' OR EXISTS (
                SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                  AND a.attname = 'workspace_id' AND NOT a.attisdropped))
        """)).all()
        if len(protected) != 25 or any(not row[1] or not row[2] or row[3] for row in protected):
            raise RuntimeError("Tenant policies or database ownership do not match this release")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Never emit SQL parameters, provider prompts or raw exceptions.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
