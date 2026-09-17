"""SQLAlchemy engine and transaction infrastructure."""

from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from domain_resolver.config.settings import Settings


def create_engine_from_url(database_url: str) -> Engine:
    """Build a PostgreSQL engine without opening a connection at import time."""
    url: URL = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("DERE requires a PostgreSQL database URL")
    return create_engine(url, pool_pre_ping=True)


def create_engine_from_settings(settings: Settings) -> Engine:
    """Build an engine from explicitly provided application settings."""
    return create_engine_from_url(settings.require_database_url())


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a non-global, non-autocommitting SQLAlchemy session factory."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide an explicit transaction that commits or rolls back and always closes."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def session_dependency(
    session_factory: sessionmaker[Session],
) -> Callable[[], Generator[Session, None, None]]:
    """Create a FastAPI-compatible request-session dependency for a supplied factory."""

    def dependency() -> Generator[Session, None, None]:
        with session_scope(session_factory) as session:
            yield session

    return dependency
