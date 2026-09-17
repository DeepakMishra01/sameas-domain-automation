"""Evaluation framework for the organization matcher.

Computes precision/recall/F1 and a reason-code breakdown from labelled pairs and
their match results. It measures only the same-organization decision and never
uses any expected-primary-domain information. It is pure (no DB/network).
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from domain_resolver.matching.matcher import MatchResult


class PairOutcome(BaseModel):
    domain_a: str
    domain_b: str
    expected_same_org: bool
    predicted_same_org: bool
    confidence: float
    reason_codes: list[str] = Field(default_factory=list)
    correct: bool


class EvaluationReport(BaseModel):
    total: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    reason_code_counts: dict[str, int] = Field(default_factory=dict)
    outcomes: list[PairOutcome] = Field(default_factory=list)


def evaluate(items: list[tuple[bool, MatchResult]]) -> EvaluationReport:
    """Build an evaluation report from ``(expected_same_org, result)`` items."""
    tp = fp = tn = fn = 0
    reason_counts: Counter[str] = Counter()
    outcomes: list[PairOutcome] = []

    for expected, result in items:
        predicted = result.same_organization
        if predicted:
            reason_counts.update(code.value for code in result.reason_codes)
        if expected and predicted:
            tp += 1
        elif not expected and predicted:
            fp += 1
        elif not expected and not predicted:
            tn += 1
        else:
            fn += 1
        outcomes.append(
            PairOutcome(
                domain_a=result.domain_a,
                domain_b=result.domain_b,
                expected_same_org=expected,
                predicted_same_org=predicted,
                confidence=result.confidence,
                reason_codes=[code.value for code in result.reason_codes],
                correct=expected == predicted,
            )
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return EvaluationReport(
        total=len(items),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        reason_code_counts=dict(sorted(reason_counts.items())),
        outcomes=outcomes,
    )
