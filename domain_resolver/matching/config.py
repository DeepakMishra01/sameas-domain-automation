"""Versioned, configuration-driven matcher weights and thresholds.

All weights and thresholds are **provisional** and configuration-driven so they
can later be evaluated and tuned against CPT-labelled data. None are claimed to
be statistically validated. The config is persisted via ``ModelVersion`` so any
stored assessment is reproducible.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from domain_resolver.matching.reason_codes import MatchReasonCode
from domain_resolver.models.entities import EvidenceStrength

MATCHER_VERSION = "org-matcher-v1"


def _default_tier_weights() -> dict[EvidenceStrength, float]:
    # Combined via noisy-OR; higher tiers can approach a confident match alone.
    return {
        EvidenceStrength.VERY_STRONG: 0.92,
        EvidenceStrength.STRONG: 0.7,
        EvidenceStrength.SUPPORTING: 0.4,
        EvidenceStrength.WEAK: 0.2,
    }


def _default_code_tiers() -> dict[MatchReasonCode, EvidenceStrength]:
    return {
        MatchReasonCode.REDIRECT: EvidenceStrength.VERY_STRONG,
        MatchReasonCode.CANONICAL_URL: EvidenceStrength.VERY_STRONG,
        MatchReasonCode.CROSS_DOMAIN_REFERENCE_MUTUAL: EvidenceStrength.VERY_STRONG,
        MatchReasonCode.CROSS_DOMAIN_REFERENCE: EvidenceStrength.STRONG,
        MatchReasonCode.SAME_EMAIL_DOMAIN: EvidenceStrength.STRONG,
        MatchReasonCode.SAME_PHONE: EvidenceStrength.STRONG,
        MatchReasonCode.SAME_SOCIAL_PROFILE: EvidenceStrength.STRONG,
        MatchReasonCode.CONTENT_FINGERPRINT_MATCH: EvidenceStrength.STRONG,
        MatchReasonCode.SIMILAR_TITLE: EvidenceStrength.SUPPORTING,
        MatchReasonCode.SIMILAR_META: EvidenceStrength.SUPPORTING,
        MatchReasonCode.SIMILAR_CONTENT: EvidenceStrength.SUPPORTING,
        MatchReasonCode.SHARED_REFERENCED_DOMAINS: EvidenceStrength.SUPPORTING,
        MatchReasonCode.DNS_OVERLAP: EvidenceStrength.SUPPORTING,
        MatchReasonCode.DOMAIN_NAME_SIMILARITY: EvidenceStrength.WEAK,
    }


def _default_negative_weights() -> dict[MatchReasonCode, float]:
    # Contradictions dampen confidence multiplicatively; a single one never
    # auto-rejects on its own (see matcher docstring).
    return {
        MatchReasonCode.DIFFERENT_EMAIL_DOMAIN: 0.3,
        MatchReasonCode.DIFFERENT_PHONE: 0.25,
    }


class MatcherConfig(BaseModel):
    """Deterministic matcher configuration; every value is provisional."""

    version: str = MATCHER_VERSION
    tier_weights: dict[EvidenceStrength, float] = Field(default_factory=_default_tier_weights)
    code_tiers: dict[MatchReasonCode, EvidenceStrength] = Field(default_factory=_default_code_tiers)
    negative_weights: dict[MatchReasonCode, float] = Field(
        default_factory=_default_negative_weights
    )

    # Decision + confidence banding (provisional; not statistically validated).
    decision_threshold: float = 0.5
    high_threshold: float = 0.8
    medium_threshold: float = 0.5

    # Deterministic similarity thresholds (token Jaccard / string ratio).
    title_similarity_threshold: float = 0.6
    meta_similarity_threshold: float = 0.6
    content_similarity_threshold: float = 0.7
    domain_name_similarity_threshold: float = 0.7

    def positive_weight(self, code: MatchReasonCode) -> float:
        return self.tier_weights[self.code_tiers[code]]

    def to_configuration(self) -> dict[str, Any]:
        """Serialise for persistence in ``ModelVersion.configuration``."""
        return self.model_dump(mode="json")


DEFAULT_MATCHER_CONFIG = MatcherConfig()
