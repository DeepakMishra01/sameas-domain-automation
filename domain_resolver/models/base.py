"""SQLAlchemy declarative base and common database helpers."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all DERE relational models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDTimestampMixin:
    """Common UUID identity and creation timestamp for persisted records."""

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )


class MutableTimestampMixin:
    """Operational ``updated_at`` for entities whose current state may change.

    This is deliberately not part of :class:`UUIDTimestampMixin`: append-only
    historical tables must never gain a mutable timestamp. ``onupdate`` refreshes
    the value on every ORM ``UPDATE`` for operational and audit visibility.
    """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
    )
