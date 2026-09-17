"""Observation exceptions and reliable failure classification.

Failures are mapped to :class:`ObservationErrorCategory` only when they can be
classified with confidence. Anything ambiguous is left uncategorised (``None``)
with the raw detail preserved, honouring "do not invent errors".
"""

from __future__ import annotations

import ssl

import httpx

from domain_resolver.models.entities import ObservationErrorCategory


class ObservationError(Exception):
    """Base class for observation-layer failures."""


class SsrfBlockedError(ObservationError):
    """Raised when a target resolves to, or is, a disallowed address."""


class DnsResolutionError(ObservationError):
    """Raised when a hostname cannot be resolved during connection setup."""


class UnsafeUrlError(ObservationError):
    """Raised for an unsupported scheme, port, or malformed target URL."""


def classify_http_exception(exc: BaseException) -> tuple[ObservationErrorCategory | None, str]:
    """Map a raised exception to a factual error category and a short detail.

    Returns ``(None, detail)`` when the failure cannot be classified reliably.
    """
    detail = f"{type(exc).__name__}: {exc}"

    if isinstance(exc, SsrfBlockedError):
        return ObservationErrorCategory.SSRF_BLOCKED, detail
    if isinstance(exc, DnsResolutionError):
        return ObservationErrorCategory.DNS_ERROR, detail
    if isinstance(exc, UnsafeUrlError):
        return ObservationErrorCategory.SSRF_BLOCKED, detail

    # TLS failures may surface directly or wrapped by httpx.ConnectError.
    if _has_ssl_cause(exc):
        return ObservationErrorCategory.SSL_ERROR, detail
    if isinstance(exc, httpx.TimeoutException):
        return ObservationErrorCategory.TIMEOUT, detail
    if isinstance(exc, httpx.ConnectError):
        return ObservationErrorCategory.CONNECTION_ERROR, detail
    if isinstance(exc, httpx.TransportError):
        return ObservationErrorCategory.CONNECTION_ERROR, detail

    return None, detail


def classify_status(status_code: int) -> ObservationErrorCategory | None:
    """Classify an HTTP status as a factual category (never a relationship claim)."""
    if status_code == 403:
        return ObservationErrorCategory.HTTP_403
    if status_code == 429:
        return ObservationErrorCategory.HTTP_429
    if 400 <= status_code < 500:
        return ObservationErrorCategory.HTTP_4XX
    if 500 <= status_code < 600:
        return ObservationErrorCategory.HTTP_5XX
    return None


def _has_ssl_cause(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False
