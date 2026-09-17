"""Alembic environment configured from DERE application settings."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from domain_resolver.config.settings import Settings
from domain_resolver.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Read the database URL from an injected test value or typed settings."""
    injected_url = config.attributes.get("database_url")
    if isinstance(injected_url, str):
        return injected_url
    return Settings().require_database_url()


def run_migrations_offline() -> None:
    """Run migrations without creating an engine."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with an isolated migration connection."""
    connectable = create_engine(database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
