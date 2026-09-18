"""Evaluation framework for primary-domain resolution.

Operates on domains already confirmed to be the same organization (it never uses
Phase 5 to decide membership, so Phase 5 false negatives cannot hide here). It
compares the resolved primary against the expected primary and reports accuracy,
coverage, confidence distribution, and the reason codes responsible. Pure.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from domain_resolver.resolution.results import PrimaryResolution, ResolutionStatus


class PrimaryOutcome(BaseModel):
    expected_primary: str
    predicted_primary: str | None
    status: ResolutionStatus
    confidence: float
    confidence_band: str
    correct: bool


class PrimaryEvaluationReport(BaseModel):
    total: int
    resolved: int
    unresolved: int
    correct: int
    incorrect: int
    coverage: float  # resolved / total
    accuracy_over_resolved: float  # correct / resolved
    overall_accuracy: float  # correct / total
    band_counts: dict[str, int] = Field(default_factory=dict)
    reason_code_counts: dict[str, int] = Field(default_factory=dict)
    outcomes: list[PrimaryOutcome] = Field(default_factory=list)


def evaluate_primary(items: list[tuple[str, PrimaryResolution]]) -> PrimaryEvaluationReport:
    """Build a report from ``(expected_primary_host, resolution)`` items."""
    resolved = correct = incorrect = 0
    bands: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    outcomes: list[PrimaryOutcome] = []

    for expected, resolution in items:
        is_resolved = resolution.status is ResolutionStatus.RESOLVED
        predicted = resolution.primary_host if is_resolved else None
        is_correct = is_resolved and predicted == expected
        if is_resolved:
            resolved += 1
            bands.update([resolution.confidence_band.value])
            for score in resolution.scores:
                if score.designation.value == "PRIMARY":
                    reasons.update(code.value for code in score.reason_codes)
            if is_correct:
                correct += 1
            else:
                incorrect += 1
        outcomes.append(
            PrimaryOutcome(
                expected_primary=expected,
                predicted_primary=predicted,
                status=resolution.status,
                confidence=resolution.confidence,
                confidence_band=resolution.confidence_band.value,
                correct=is_correct,
            )
        )

    total = len(items)
    return PrimaryEvaluationReport(
        total=total,
        resolved=resolved,
        unresolved=total - resolved,
        correct=correct,
        incorrect=incorrect,
        coverage=round(resolved / total, 4) if total else 0.0,
        accuracy_over_resolved=round(correct / resolved, 4) if resolved else 0.0,
        overall_accuracy=round(correct / total, 4) if total else 0.0,
        band_counts=dict(sorted(bands.items())),
        reason_code_counts=dict(sorted(reasons.items())),
        outcomes=outcomes,
    )
