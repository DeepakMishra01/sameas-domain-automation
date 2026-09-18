"""Phase 6 primary-domain resolution.

Given a group of domains Phase 5 confirmed to belong to one organization, decides
which is PRIMARY (and which are SECONDARY) from directional evidence only —
never from name length, age, TLD, or popularity. Deterministic and explainable;
no network/DNS/LLM/embeddings. It refuses to force a primary when evidence is
mutual, ambiguous, or absent (REVIEW_REQUIRED).

This answers a different question than Phase 5: Phase 5 asks "are these the same
organization?"; Phase 6 asks "which one is primary?". It is also separate from
the final CPT accept/reject decision (Phase 7).
"""

from domain_resolver.resolution.config import (
    DEFAULT_RESOLVER_CONFIG,
    RESOLVER_VERSION,
    ResolverConfig,
)
from domain_resolver.resolution.evaluation import PrimaryEvaluationReport, evaluate_primary
from domain_resolver.resolution.reason_codes import PrimaryReasonCode
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import (
    DomainScore,
    PrimaryConfidenceBand,
    PrimaryDesignation,
    PrimaryResolution,
    ResolutionStatus,
)
from domain_resolver.resolution.service import run_primary_resolution

__all__ = [
    "DEFAULT_RESOLVER_CONFIG",
    "RESOLVER_VERSION",
    "DomainScore",
    "PrimaryConfidenceBand",
    "PrimaryDesignation",
    "PrimaryDomainResolver",
    "PrimaryEvaluationReport",
    "PrimaryReasonCode",
    "PrimaryResolution",
    "ResolutionStatus",
    "ResolverConfig",
    "evaluate_primary",
    "run_primary_resolution",
]
