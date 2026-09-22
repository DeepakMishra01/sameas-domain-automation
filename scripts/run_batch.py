#!/usr/bin/env python
"""Run a batch of domain pairs from an Excel file through the full pipeline.

For each row (Company ID, Domain1, Domain2) it observes both domains (Phase 3),
extracts features (Phase 4), decides same-organization (Phase 5), and — only when
they are the same organization — resolves the primary domain (Phase 6). Results
are written to a CSV (openable in Excel), one row at a time so partial progress
is saved and the run can be interrupted or done in chunks.

Requires DERE_DATABASE_URL. Makes outbound web requests via the SSRF-safe
observer; matching/resolution make no network calls.

Usage:
  DERE_DATABASE_URL=... python scripts/run_batch.py INPUT.xlsx OUTPUT.csv \
      [--start N] [--limit M]
"""

from __future__ import annotations

import argparse
import csv
from uuid import uuid4

import openpyxl

from domain_resolver.config.settings import get_settings
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.models.entities import Company, Domain
from domain_resolver.normalization import normalize_domain
from domain_resolver.observation.dns_observer import DnsObserver
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.service import run_domain_observation
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


def _prepare(session: object, company_id: object, host: str) -> DomainFeatureView | None:
    settings = get_settings()
    domains = SqlAlchemyDomainRepository(session)
    domain = domains.get_by_hostname(host) or domains.create(Domain(hostname=host))
    observation = run_domain_observation(
        session,
        company_id=company_id,  # type: ignore[arg-type]
        domain_id=domain.id,
        idempotency_key=uuid4().hex,
        collector_version=settings.collector_version,
        dns_observer=DnsObserver(),
        http_observer=HttpObserver(),
    )
    run_feature_extraction(
        session,
        observation_id=observation.id,
        extractor=FeatureExtractor(settings.feature_extractor_version),
    )
    snapshots = SqlAlchemyObservationFeatureRepository(session).list_by_domain(domain.id)
    return DomainFeatureView.from_snapshot(snapshots[-1], host) if snapshots else None


def _process_row(
    factory: object,
    matcher: OrganizationMatcher,
    resolver: PrimaryDomainResolver,
    row: dict[str, str],
) -> dict[str, object]:
    out: dict[str, object] = {c: "" for c in COLUMNS}
    out["company_id"] = row["company_id"]
    out["domain1_raw"] = row["domain1_raw"]
    out["domain2_raw"] = row["domain2_raw"]
    try:
        host_a = normalize_domain(row["domain1_raw"])
        host_b = normalize_domain(row["domain2_raw"])
    except ValueError as exc:
        out["note"] = f"invalid domain: {exc}"
        return out
    out["domain1"], out["domain2"] = host_a, host_b
    if host_a == host_b:
        out["note"] = "same host after normalization"
        return out

    try:
        with session_scope(factory) as session:  # type: ignore[arg-type]
            company = Company(
                external_company_id=f"batch-{row['company_id']}-{uuid4().hex[:6]}",
                name_raw=f"Batch {row['company_id']}",
                name_normalized=f"batch {row['company_id']}",
            )
            session.add(company)
            session.flush()
            view_a = _prepare(session, company.id, host_a)
            view_b = _prepare(session, company.id, host_b)
    except Exception as exc:  # noqa: BLE001 - record the failure, keep going
        out["note"] = f"error: {type(exc).__name__}: {exc}"
        return out

    if view_a is None or view_b is None:
        out["note"] = "no observation for one or both domains"
        return out

    match = matcher.match(view_a, view_b)
    out["same_organization"] = match.same_organization
    out["match_confidence"] = match.confidence
    out["match_reason_codes"] = ",".join(code.value for code in match.reason_codes)

    if match.same_organization:
        resolution = resolver.resolve([view_a, view_b])
        out["primary_status"] = resolution.status.value
        out["primary_confidence"] = resolution.confidence
        out["primary_domain"] = (
            resolution.primary_host if resolution.status is ResolutionStatus.RESOLVED else ""
        )
    else:
        out["primary_status"] = "N/A (not same organization)"
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="input .xlsx (Company ID, Domain1, Domain2)")
    parser.add_argument("output", help="output .csv")
    parser.add_argument("--start", type=int, default=0, help="0-based row offset to start at")
    parser.add_argument("--limit", type=int, default=25, help="max rows to process")
    args = parser.parse_args()

    workbook = openpyxl.load_workbook(args.input, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    all_rows = list(sheet.iter_rows(values_only=True))[1:]  # skip header
    rows = all_rows[args.start : args.start + args.limit]

    settings = get_settings()
    factory = create_session_factory(create_engine_from_settings(settings))
    matcher = OrganizationMatcher()
    resolver = PrimaryDomainResolver()

    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for index, raw in enumerate(rows, start=args.start + 1):
            company_id = "" if raw[0] is None else str(raw[0]).replace(".0", "")
            row = {
                "company_id": company_id,
                "domain1_raw": str(raw[1] or "").strip(),
                "domain2_raw": str(raw[2] or "").strip(),
            }
            result = _process_row(factory, matcher, resolver, row)
            writer.writerow(result)
            handle.flush()
            print(
                f"[{index}] {row['domain1_raw']} / {row['domain2_raw']} -> "
                f"same_org={result['same_organization']} primary={result['primary_domain']} "
                f"{('| ' + str(result['note'])) if result['note'] else ''}"
            )
    print(f"\nDone. Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
