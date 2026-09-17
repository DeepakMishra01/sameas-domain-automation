"""Deterministic, explainable organization matcher.

Answers only "do these two domains belong to the same organization?" from
already-collected features. It never selects a primary domain, calls an LLM, uses
embeddings/ML, or makes any network call. Every positive decision is explainable
via the reason codes and evidence that produced it.

Confidence is a deterministic noisy-OR combination of the fired positive signals'
configured weights, multiplicatively dampened by contradictory signals. Weights
and thresholds are provisional and configuration-driven (see
:class:`MatcherConfig`); no value is claimed to be statistically validated. A
single contradiction never auto-rejects on its own — it only lowers confidence.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from domain_resolver.matching.config import DEFAULT_MATCHER_CONFIG, MatcherConfig
from domain_resolver.matching.pair_features import build_pairwise_features
from domain_resolver.matching.reason_codes import NEGATIVE_CODES, POSITIVE_CODES, MatchReasonCode
from domain_resolver.matching.views import DomainFeatureView


class ConfidenceBand(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MatchResult(BaseModel):
    """Explainable pairwise same-organization result (canonical pair order)."""

    domain_a_id: UUID
    domain_b_id: UUID
    domain_a: str
    domain_b: str
    same_organization: bool
    confidence: float
    confidence_band: ConfidenceBand
    reason_codes: list[MatchReasonCode] = Field(default_factory=list)
    negative_reason_codes: list[MatchReasonCode] = Field(default_factory=list)
    matcher_version: str
    features: dict[str, object] = Field(default_factory=dict)


def _noisy_or(weights: list[float]) -> float:
    product = 1.0
    for weight in weights:
        product *= 1.0 - weight
    return 1.0 - product


class OrganizationMatcher:
    def __init__(self, config: MatcherConfig = DEFAULT_MATCHER_CONFIG) -> None:
        self._config = config

    @property
    def version(self) -> str:
        return self._config.version

    @property
    def config(self) -> MatcherConfig:
        return self._config

    def match(self, view_a: DomainFeatureView, view_b: DomainFeatureView) -> MatchResult:
        # Canonicalize input order so a<b, matching the DomainRelationship rule.
        if view_a.domain_id > view_b.domain_id:
            view_a, view_b = view_b, view_a

        pairwise = build_pairwise_features(view_a, view_b, self._config)
        fired = pairwise.codes()
        positive = [c for c in fired if c in POSITIVE_CODES]
        negative = [c for c in fired if c in NEGATIVE_CODES]

        positive_confidence = _noisy_or([self._config.positive_weight(c) for c in positive])
        negative_confidence = _noisy_or([self._config.negative_weights[c] for c in negative])
        confidence = round(positive_confidence * (1.0 - negative_confidence), 4)

        same_organization = confidence >= self._config.decision_threshold
        band = self._band(confidence)

        return MatchResult(
            domain_a_id=view_a.domain_id,
            domain_b_id=view_b.domain_id,
            domain_a=view_a.host,
            domain_b=view_b.host,
            same_organization=same_organization,
            confidence=confidence,
            confidence_band=band,
            reason_codes=positive,
            negative_reason_codes=negative,
            matcher_version=self._config.version,
            features=pairwise.model_dump(mode="json"),
        )

    def _band(self, confidence: float) -> ConfidenceBand:
        if confidence >= self._config.high_threshold:
            return ConfidenceBand.HIGH
        if confidence >= self._config.medium_threshold:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW
