"""Safe domain observation (Phase 3).

Collects factual DNS and HTTP observations from CPT-supplied candidate domains.
This package answers only "what did we observe?" — it performs no same-as
matching, organization resolution, scoring, or primary-domain selection.
"""

from domain_resolver.observation.dns_observer import DnsObserver
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.limits import DEFAULT_LIMITS, ObservationLimits
from domain_resolver.observation.results import (
    DnsObservation,
    HttpObservation,
    ObservationResult,
)
from domain_resolver.observation.service import (
    DomainNotFoundError,
    run_domain_observation,
)

__all__ = [
    "DEFAULT_LIMITS",
    "DnsObservation",
    "DnsObserver",
    "DomainNotFoundError",
    "HttpObservation",
    "HttpObserver",
    "ObservationLimits",
    "ObservationResult",
    "run_domain_observation",
]
