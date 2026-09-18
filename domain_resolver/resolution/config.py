"""Versioned, configuration-driven primary-domain resolver settings.

All weights and thresholds are **provisional** and configuration-driven so they
can be tuned against CPT-labelled data later. None is claimed to be statistically
validated. The config is persisted via ``ModelVersion`` for reproducibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from domain_resolver.models.entities import EvidenceStrength
from domain_resolver.resolution.reason_codes import PrimaryReasonCode

RESOLVER_VERSION = "primary-v1"


def _default_tier_weights() -> dict[EvidenceStrength, float]:
    return {
        EvidenceStrength.VERY_STRONG: 0.92,
        EvidenceStrength.STRONG: 0.7,
        EvidenceStrength.SUPPORTING: 0.45,
        EvidenceStrength.WEAK: 0.25,
    }


def _default_code_tiers() -> dict[PrimaryReasonCode, EvidenceStrength]:
    return {
        PrimaryReasonCode.REDIRECT_TARGET: EvidenceStrength.VERY_STRONG,
        PrimaryReasonCode.CANONICAL_TARGET: EvidenceStrength.VERY_STRONG,
        PrimaryReasonCode.ACTIVE_WEBSITE: EvidenceStrength.SUPPORTING,
        PrimaryReasonCode.SELF_CANONICAL: EvidenceStrength.SUPPORTING,
        PrimaryReasonCode.REFERENCED_BY_PEER: EvidenceStrength.WEAK,
    }


def _default_negative_weights() -> dict[PrimaryReasonCode, float]:
    # A domain that redirects/canonicals to a peer is deferring to it, so its own
    # primary score is strongly dampened (it is a pointer, not the destination).
    return {
        PrimaryReasonCode.REDIRECTS_AWAY: 0.9,
        PrimaryReasonCode.CANONICAL_AWAY: 0.85,
        # A one-way link (A links to B, B does not link back) is directional but
        # weaker than a redirect/canonical, so it dampens A's score less.
        PrimaryReasonCode.REFERENCES_AWAY: 0.6,
    }


class ResolverConfig(BaseModel):
    """Deterministic primary-domain resolver configuration; all values provisional."""

    version: str = RESOLVER_VERSION
    tier_weights: dict[EvidenceStrength, float] = Field(default_factory=_default_tier_weights)
    code_tiers: dict[PrimaryReasonCode, EvidenceStrength] = Field(
        default_factory=_default_code_tiers
    )
    negative_weights: dict[PrimaryReasonCode, float] = Field(
        default_factory=_default_negative_weights
    )

    # A domain is only resolved PRIMARY when its score clears this bar AND beats
    # the runner-up by at least this margin (a clear, unambiguous winner).
    decision_threshold: float = 0.5
    margin_threshold: float = 0.15

    # Confidence banding (provisional; not statistically validated).
    high_threshold: float = 0.8
    medium_threshold: float = 0.5

    def positive_weight(self, code: PrimaryReasonCode) -> float:
        return self.tier_weights[self.code_tiers[code]]

    def to_configuration(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


DEFAULT_RESOLVER_CONFIG = ResolverConfig()
