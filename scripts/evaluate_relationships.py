#!/usr/bin/env python
"""Evaluate the relationship classifier against a labelled set.

Reads a labelled CSV (``domain_a,domain_b,expected_type`` — ``expected_subtype``
and ``expected_primary`` optional), classifies each pair from ALREADY-STORED
Phase 4 features (no crawling), and reports per-type precision/recall/F1, the
confusion matrix, primary-domain accuracy, and — most importantly (SOP §22) — the
count of SAME_AS false positives (a PART_OF/ACQUIRED/UNRELATED pair wrongly
called SAME_AS). Read-only against the database.

Usage:
  DERE_DATABASE_URL=... python scripts/evaluate_relationships.py LABELS.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter

from domain_resolver.classification.classifier import RelationshipClassifier
from domain_resolver.classification.relationship_types import RelationshipType
from domain_resolver.config.settings import get_settings
from domain_resolver.features.results import FeatureSet
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.normalization import normalize_domain
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDomainRepository,
    SqlAlchemyObservationFeatureRepository,
)

TYPES = [t.value for t in RelationshipType]


def _view(session: object, host: str) -> DomainFeatureView | None:
    domain = SqlAlchemyDomainRepository(session).get_by_hostname(host)
    if domain is None:
        return None
    snaps = SqlAlchemyObservationFeatureRepository(session).list_by_domain(domain.id)
    if not snaps:
        return None
    return DomainFeatureView(
        domain_id=domain.id,
        observation_id=snaps[-1].observation_id,
        host=host,
        features=FeatureSet.model_validate(snaps[-1].features),
    )


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", help="labelled CSV: domain_a,domain_b,expected_type[,...]")
    args = parser.parse_args()

    with open(args.labels, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    factory = create_session_factory(create_engine_from_settings(get_settings()))
    matcher, classifier = OrganizationMatcher(), RelationshipClassifier()

    confusion: Counter[tuple[str, str]] = Counter()  # (gold, predicted)
    primary_total = primary_correct = 0
    skipped = 0

    with session_scope(factory) as session:
        for row in rows:
            gold = row["expected_type"].strip().upper()
            try:
                host_a = normalize_domain(row["domain_a"])
                host_b = normalize_domain(row["domain_b"])
            except ValueError:
                skipped += 1
                continue
            view_a, view_b = _view(session, host_a), _view(session, host_b)
            if view_a is None or view_b is None:
                skipped += 1
                continue
            match = matcher.match(view_a, view_b)
            result = classifier.classify(view_a, view_b, match)
            predicted = result.relationship_type.value
            confusion[(gold, predicted)] += 1
            expected_primary = (row.get("expected_primary") or "").strip()
            if expected_primary:
                primary_total += 1
                if result.primary_host == normalize_domain(expected_primary):
                    primary_correct += 1

    evaluated = sum(confusion.values())
    print(f"Evaluated {evaluated} pairs ({skipped} skipped: unobserved/invalid)\n")

    print("Per-type precision / recall / F1:")
    for t in TYPES:
        tp = confusion[(t, t)]
        fp = sum(c for (g, p), c in confusion.items() if p == t and g != t)
        fn = sum(c for (g, p), c in confusion.items() if g == t and p != t)
        precision, recall, f1 = _prf(tp, fp, fn)
        support = sum(c for (g, _), c in confusion.items() if g == t)
        print(f"  {t:16} P={precision:<6} R={recall:<6} F1={f1:<6} support={support}")

    same_as_fp = sum(c for (g, p), c in confusion.items() if p == "SAME_AS" and g != "SAME_AS")
    print(f"\nSAME_AS false positives (CRITICAL): {same_as_fp}")
    if primary_total:
        print(
            f"Primary-domain accuracy: {primary_correct}/{primary_total} "
            f"({round(100 * primary_correct / primary_total, 1)}%)"
        )

    print("\nConfusion (gold -> predicted):")
    for gold in TYPES:
        preds = {p: c for (g, p), c in confusion.items() if g == gold}
        if preds:
            print(f"  {gold:16} -> " + ", ".join(f"{p}:{c}" for p, c in sorted(preds.items())))


if __name__ == "__main__":
    main()
