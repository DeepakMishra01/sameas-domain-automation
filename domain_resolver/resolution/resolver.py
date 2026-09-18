"""Deterministic, explainable primary-domain resolver.

Given domains already confirmed (by Phase 5) to belong to one organization, it
decides which is PRIMARY from directional evidence only — never from name length,
age, TLD, or popularity. It consumes stored features; no network/DNS/LLM.

It refuses to force an answer: mutual/cyclic pointing, ambiguous scores, or an
absence of directional evidence yield ``REVIEW_REQUIRED`` with every domain left
``UNRESOLVED`` rather than a guessed primary or blindly-labelled secondaries.
"""

from __future__ import annotations

from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.resolution.config import DEFAULT_RESOLVER_CONFIG, ResolverConfig
from domain_resolver.resolution.reason_codes import PrimaryReasonCode
from domain_resolver.resolution.results import (
    DomainScore,
    PrimaryConfidenceBand,
    PrimaryDesignation,
    PrimaryResolution,
    ResolutionStatus,
)
from domain_resolver.resolution.signals import compute_group_signals


def _noisy_or(weights: list[float]) -> float:
    product = 1.0
    for weight in weights:
        product *= 1.0 - weight
    return 1.0 - product


class PrimaryDomainResolver:
    def __init__(self, config: ResolverConfig = DEFAULT_RESOLVER_CONFIG) -> None:
        self._config = config

    @property
    def version(self) -> str:
        return self._config.version

    @property
    def config(self) -> ResolverConfig:
        return self._config

    def resolve(self, views: list[DomainFeatureView]) -> PrimaryResolution:
        group = compute_group_signals(views)
        scores: list[DomainScore] = []
        for view in views:
            ds = group.signals[view.domain_id]
            positive = sorted(ds.positive)
            negative = sorted(ds.negative)
            pos = _noisy_or([self._config.positive_weight(c) for c in positive])
            neg = _noisy_or([self._config.negative_weights[c] for c in negative])
            scores.append(
                DomainScore(
                    domain_id=view.domain_id,
                    host=view.host,
                    primary_score=round(pos * (1.0 - neg), 4),
                    designation=PrimaryDesignation.UNRESOLVED,
                    reason_codes=positive,
                    negative_reason_codes=negative,
                )
            )

        ranked = sorted(scores, key=lambda s: (-s.primary_score, str(s.domain_id)))
        top = ranked[0] if ranked else None
        runner = ranked[1] if len(ranked) > 1 else None
        margin = (
            round(top.primary_score - (runner.primary_score if runner else 0.0), 4) if top else 0.0
        )

        resolved = bool(
            top is not None
            and top.reason_codes  # winner must have real positive primary evidence
            and top.primary_score >= self._config.decision_threshold
            and (runner is None or margin >= self._config.margin_threshold)
            and not group.conflicts
        )

        if resolved and top is not None:
            for score in scores:
                score.designation = (
                    PrimaryDesignation.PRIMARY
                    if score.domain_id == top.domain_id
                    else PrimaryDesignation.SECONDARY
                )
            return PrimaryResolution(
                resolver_version=self._config.version,
                status=ResolutionStatus.RESOLVED,
                primary_domain_id=top.domain_id,
                primary_host=top.host,
                confidence=top.primary_score,
                confidence_band=self._band(top.primary_score),
                margin=margin,
                scores=scores,
                conflicts=group.conflicts,
            )

        confidence = top.primary_score if top is not None else 0.0
        return PrimaryResolution(
            resolver_version=self._config.version,
            status=ResolutionStatus.REVIEW_REQUIRED,
            primary_domain_id=None,
            primary_host=None,
            confidence=confidence,
            confidence_band=self._band(confidence),
            margin=margin,
            scores=scores,
            conflicts=group.conflicts,
        )

    def _band(self, confidence: float) -> PrimaryConfidenceBand:
        if confidence >= self._config.high_threshold:
            return PrimaryConfidenceBand.HIGH
        if confidence >= self._config.medium_threshold:
            return PrimaryConfidenceBand.MEDIUM
        return PrimaryConfidenceBand.LOW


__all__ = ["PrimaryDomainResolver", "PrimaryReasonCode"]
