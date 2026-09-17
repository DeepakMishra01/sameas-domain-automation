"""Bounded, centrally-defined limits for safe domain observation.

Every network and parsing bound lives here so the observer is deterministic and
auditable, and so tests can supply tight limits without touching the code paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ObservationLimits:
    """Immutable bounds applied to every observation attempt."""

    allowed_schemes: frozenset[str] = frozenset({"http", "https"})
    allowed_ports: frozenset[int] = frozenset({80, 443})

    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    write_timeout: float = 5.0
    pool_timeout: float = 5.0
    # Wall-clock ceiling across the whole redirect chain for one observation.
    total_timeout: float = 25.0

    max_redirects: int = 5
    max_body_bytes: int = 2_000_000
    max_text_chars: int = 20_000
    max_links: int = 200

    dns_timeout: float = 3.0
    dns_lifetime: float = 6.0

    # A neutral, honest, cookie-free identifier. Never carries credentials.
    user_agent: str = field(
        default="DERE-DomainObserver/1.0 (+domain-observation; no-cookies; no-js)"
    )


DEFAULT_LIMITS = ObservationLimits()
