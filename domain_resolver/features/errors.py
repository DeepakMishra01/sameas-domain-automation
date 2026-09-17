"""Structured, factual extraction warning categories for Phase 4.

Extraction never crashes on malformed observation content: each recoverable
problem becomes a structured warning attached to the feature snapshot rather
than a silently discarded value or a raised exception out of the worker.
"""

from __future__ import annotations

from enum import StrEnum


class ExtractionWarningCategory(StrEnum):
    MALFORMED_URL = "MALFORMED_URL"
    MALFORMED_HTML = "MALFORMED_HTML"
    INVALID_UNICODE = "INVALID_UNICODE"
    INVALID_EMAIL = "INVALID_EMAIL"
    INVALID_PHONE = "INVALID_PHONE"
    OVERSIZED_FIELD = "OVERSIZED_FIELD"
    UNSUPPORTED_ENCODING = "UNSUPPORTED_ENCODING"
    MALFORMED_OBSERVATION = "MALFORMED_OBSERVATION"


class FeatureExtractionError(Exception):
    """Raised only for unrecoverable extraction failures (e.g. missing observation)."""


class ObservationPayloadError(FeatureExtractionError):
    """Raised when a stored observation payload cannot be parsed at all."""
