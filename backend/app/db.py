from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.base import Base  # noqa: F401
from app.config import get_settings


settings = get_settings()
database_url = settings.database_url
engine_options = {"pool_pre_ping": True, "hide_parameters": True}
if make_url(database_url).get_backend_name() == "sqlite":
    # SQLite is used for local development; the lifespan worker shares the
    # same file-backed database from a separate thread.
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}
else:
    engine_options.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                          pool_timeout=10, pool_recycle=300,
                          connect_args={"connect_timeout": 10, "application_name": f"marketmind-{settings.service_role}"})
engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def set_db_scope(session: Session, *, workspace_id: str | None = None,
                 user_id: str | None = None, source_token_hash: str | None = None) -> None:
    """Use only after authentication, or for a persisted job's tenant.

    SET LOCAL is reapplied after every commit and cleared on pool return, so
    concurrent requests and reused connections cannot inherit another tenant.
    """
    for key, value in (("workspace_id", workspace_id), ("user_id", user_id),
                       ("source_token_hash", source_token_hash)):
        if value is not None:
            session.info[key] = value
    if session.in_transaction() and session.get_bind().dialect.name == "postgresql":
        _apply_scope(session.info, session.connection())


def _apply_scope(info: dict, connection) -> None:
    for key in ("workspace_id", "user_id", "source_token_hash"):
        connection.execute(text("SELECT set_config(:key, :value, true)"),
                           {"key": f"app.{key}", "value": info.get(key, "")})


@event.listens_for(Session, "after_begin")
def transaction_scope(session, transaction, connection):
    if connection.dialect.name == "postgresql":
        _apply_scope(session.info, connection)


def get_db():
    with SessionLocal() as session:
        yield session
