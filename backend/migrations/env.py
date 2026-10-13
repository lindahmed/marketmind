from alembic import context
from alembic.ddl.postgresql import PostgresqlImpl
from sqlalchemy import String, create_engine, inspect, pool, text

from app.config import get_settings
from app.base import Base
from app import models  # noqa: F401

config = context.config
target_metadata = Base.metadata


class MarketMindPostgresqlImpl(PostgresqlImpl):
    # Preserve existing revision IDs (0013 exceeds Alembic's default 32 chars).
    __dialect__ = "postgresql"

    def version_table_impl(self, **kwargs):
        table = super().version_table_impl(**kwargs)
        table.c.version_num.type = String(64)
        return table


def prepare_version_table(connection):
    if connection.dialect.name == "postgresql" and inspect(connection).has_table("alembic_version"):
        connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(64)"))


def run_migrations_offline():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    existing = config.attributes.get("connection")
    if existing is not None:
        prepare_version_table(existing)
        context.configure(connection=existing, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.begin() as connection:
        prepare_version_table(connection)
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
