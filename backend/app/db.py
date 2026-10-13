from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


database_url = get_settings().database_url
engine_options = {"pool_pre_ping": True}
if make_url(database_url).get_backend_name() == "sqlite":
    # SQLite is used for local development; the lifespan worker shares the
    # same file-backed database from a separate thread.
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}
engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session
