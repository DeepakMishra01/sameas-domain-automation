"""Structured, secret-safe logging for the observation lifecycle.

Emits compact ``key=value`` events with stable identifiers (company_id,
domain_id, observation_id, job_id, collector_version). It never logs response
bodies, headers with credentials, or secrets — callers pass only identifiers and
factual, bounded fields.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger("dere.observation")

# Fields that must never be logged even if a caller passes them.
_FORBIDDEN_FIELDS = frozenset({"body", "content", "password", "token", "secret", "authorization"})


def log_event(event: str, **fields: Any) -> None:
    """Log a single structured observation event at INFO level."""
    _emit(logging.INFO, event, fields)


def log_failure(event: str, **fields: Any) -> None:
    """Log a structured observation failure at WARNING level."""
    _emit(logging.WARNING, event, fields)


def _emit(level: int, event: str, fields: dict[str, Any]) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if key.lower() in _FORBIDDEN_FIELDS or value is None:
            continue
        parts.append(f"{key}={value}")
    _LOGGER.log(level, " ".join(parts))
