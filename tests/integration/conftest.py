"""PostgreSQL-only integration-test fixtures.

Set DERE_TEST_DATABASE_URL to a disposable database. Tests intentionally skip
instead of substituting SQLite because they validate PostgreSQL migrations.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from domain_resolver.config.settings import Settings
from domain_resolver.infrastructure.database import create_engine_from_url

PROJECT_ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = Settings().test_database_url
    if url is None:
        pytest.skip("DERE_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return url


@pytest.fixture
def alembic_config(test_database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["database_url"] = test_database_url
    return config


@pytest.fixture
def migrated_engine(
    alembic_config: Config, test_database_url: str
) -> Generator[Engine, None, None]:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    engine = create_engine_from_url(test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()
