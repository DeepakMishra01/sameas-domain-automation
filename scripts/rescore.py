#!/usr/bin/env python
"""Re-score domain pairs from ALREADY-STORED features (no crawling).

Same output as run_batch, but instead of observing the web it reuses the latest
stored Phase 4 features for each domain and re-runs only matching (Phase 5) and
primary resolution (Phase 6). Use this to regenerate results after a resolver/
matcher change without re-observing. Read-only against the database.

Usage:
  DERE_DATABASE_URL=... python scripts/rescore.py INPUT.xlsx OUTPUT.csv [--limit M]
"""

from __future__ import annotations

import argparse
import csv

import openpyxl

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
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import ResolutionStatus

COLUMNS = [
    "company_id",
    "domain1_raw",
    "domain2_raw",
    "domain1",
    "domain2",
    "same_organization",
    "match_confidence",
    "match_reason_codes",
    "primary_domain",
    "primary_status",
    "primary_confidence",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--limit", type=int, default=100000)
    args = parser.parse_args()

    # Accept either the original .xlsx (Company ID, Domain1, Domain2) or a prior
    # results .csv (company_id, domain1_raw, domain2_raw).
    if args.input.lower().endswith(".csv"):
        with open(args.input, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = [
                (r.get("company_id"), r.get("domain1_raw"), r.get("domain2_raw")) for r in reader
            ][: args.limit]
    else:
        wb = openpyxl.load_workbook(args.input, read_only=True, data_only=True)
        rows = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))[1:][: args.limit]

    factory = create_session_factory(create_engine_from_settings(get_settings()))
    matcher, resolver = OrganizationMatcher(), PrimaryDomainResolver()

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
            out["same_organization"] = match.same_organization
            out["match_confidence"] = match.confidence
            out["match_reason_codes"] = ",".join(c.value for c in match.reason_codes)
            if match.same_organization:
                res = resolver.resolve([view_a, view_b])
                out["primary_status"] = res.status.value
                out["primary_confidence"] = res.confidence
                out["primary_domain"] = (
                    res.primary_host if res.status is ResolutionStatus.RESOLVED else ""
                )
            else:
                out["primary_status"] = "N/A (not same organization)"
            writer.writerow(out)
            written += 1
    print(f"Re-scored {written} rows -> {args.output}")


if __name__ == "__main__":
    main()
