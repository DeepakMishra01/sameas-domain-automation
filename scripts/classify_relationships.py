#!/usr/bin/env python
"""Classify domain pairs into SAME_AS / PART_OF / ACQUIRED / UNRELATED / REVIEW.

Reads ALREADY-STORED Phase 4 features (no crawling), runs the Phase 5 matcher to
detect relatedness, then the deterministic relationship classifier to assign the
type, primary/secondary, and an explanation. Read-only against the database.

Output columns follow the CPT SOP (§17). Use this to (re)classify a large batch
after a classifier change without re-observing.

Usage:
  DERE_DATABASE_URL=... python scripts/classify_relationships.py INPUT OUTPUT.csv [--limit M]

INPUT may be the original .xlsx (Company ID, Domain1, Domain2) or a prior
results .csv (company_id, domain1_raw, domain2_raw).
"""

from __future__ import annotations

import argparse
import csv

import openpyxl

from domain_resolver.classification.classifier import RelationshipClassifier
from domain_resolver.config.settings import get_settings
from domain_resolver.dataset_columns import resolve_columns
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

COLUMNS = [
    "company_id",
    "domain1_raw",
    "domain2_raw",
    "domain1",
    "domain2",
    "feed_sector",
    "relationship_type",
    "relationship_subtype",
    "primary_domain",
    "secondary_domain",
    "parent_domain",
    "acquirer_domain",
    "acquired_domain",
    "direction",
    "confidence",
    "confidence_band",
    "reason_codes",
    "explanation",
    "note",
]


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


def _load_rows(path: str, limit: int) -> list[tuple[object, object, object, object]]:
    """Return (company_id, domain1_raw, domain2_raw, feed_sector) rows.

    Columns are resolved by header name, so a spreadsheet with or without a Feed
    Sector column (in any position) is read correctly.
    """
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8") as handle:
            return [
                (
                    r.get("company_id"),
                    r.get("domain1_raw"),
                    r.get("domain2_raw"),
                    r.get("feed_sector"),
                )
                for r in csv.DictReader(handle)
            ][:limit]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    all_rows = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))
    if not all_rows:
        return []
    col = resolve_columns(all_rows[0])
    sector_i = col.get("sector")
    out: list[tuple[object, object, object, object]] = []
    for raw in all_rows[1:][:limit]:
        out.append(
            (
                raw[col["company"]] if len(raw) > col["company"] else None,
                raw[col["domain1"]] if len(raw) > col["domain1"] else None,
                raw[col["domain2"]] if len(raw) > col["domain2"] else None,
                raw[sector_i] if sector_i is not None and len(raw) > sector_i else None,
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--limit", type=int, default=100000)
    args = parser.parse_args()

    rows = _load_rows(args.input, args.limit)
    factory = create_session_factory(create_engine_from_settings(get_settings()))
    matcher, classifier = OrganizationMatcher(), RelationshipClassifier()

    written = 0
    with (
        open(args.output, "w", newline="", encoding="utf-8") as handle,
        session_scope(factory) as session,
    ):
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for raw in rows:
            out: dict[str, object] = {c: "" for c in COLUMNS}
            out["company_id"] = "" if raw[0] is None else str(raw[0]).replace(".0", "")
            out["domain1_raw"] = str(raw[1] or "").strip()
            out["domain2_raw"] = str(raw[2] or "").strip()
            out["feed_sector"] = str(raw[3] or "").strip()
            try:
                host_a = normalize_domain(out["domain1_raw"])
                host_b = normalize_domain(out["domain2_raw"])
            except ValueError as exc:
                out["note"] = f"invalid domain: {exc}"
                writer.writerow(out)
                written += 1
                continue
            out["domain1"], out["domain2"] = host_a, host_b
            if host_a == host_b:
                out["note"] = "same host after normalization"
                writer.writerow(out)
                written += 1
                continue
            view_a, view_b = _view(session, host_a), _view(session, host_b)
            if view_a is None or view_b is None:
                out["note"] = "no stored observation for one or both domains"
                writer.writerow(out)
                written += 1
                continue

            match = matcher.match(view_a, view_b)
            result = classifier.classify(view_a, view_b, match)
            out["relationship_type"] = result.relationship_type.value
            out["relationship_subtype"] = (
                result.relationship_subtype.value if result.relationship_subtype else ""
            )
            out["primary_domain"] = result.primary_host or ""
            out["secondary_domain"] = result.secondary_host or ""
            out["parent_domain"] = result.parent_host or ""
            out["acquirer_domain"] = result.acquirer_host or ""
            out["acquired_domain"] = result.acquired_host or ""
            out["direction"] = result.direction.value
            out["confidence"] = result.confidence
            out["confidence_band"] = result.confidence_band.value
            out["reason_codes"] = ",".join(c.value for c in result.reason_codes)
            out["explanation"] = result.explanation
            writer.writerow(out)
            written += 1
    print(f"Classified {written} rows -> {args.output}")


if __name__ == "__main__":
    main()
