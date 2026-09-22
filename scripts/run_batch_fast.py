#!/usr/bin/env python
"""Faster batch runner: checks many domain pairs concurrently.

Same output as run_batch.py, but processes rows in parallel (network-bound work,
so threads give a big speed-up) and uses shorter timeouts so dead/slow sites fail
fast. Domains are pre-created up front so parallel workers never race to insert
the same domain. Writes results as each pair finishes; safe to interrupt.

Usage:
  DERE_DATABASE_URL=... python scripts/run_batch_fast.py INPUT.xlsx OUTPUT.csv \
      [--start N] [--limit M] [--workers W]
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from uuid import uuid4

import openpyxl
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from domain_resolver.config.settings import get_settings
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.models.entities import Company, Domain
from domain_resolver.normalization import normalize_domain
from domain_resolver.observation.dns_observer import DnsObserver
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.limits import DEFAULT_LIMITS
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

# Shorter timeouts: dead/slow sites fail fast instead of waiting ~25s.
TIGHT = replace(
    DEFAULT_LIMITS,
    connect_timeout=3.0,
    read_timeout=6.0,
    write_timeout=3.0,
    pool_timeout=3.0,
    total_timeout=12.0,
)

MATCHER = OrganizationMatcher()
RESOLVER = PrimaryDomainResolver()
EXTRACTOR = FeatureExtractor(get_settings().feature_extractor_version)


def _prepare(session: object, company_id: object, host: str) -> DomainFeatureView | None:
    domains = SqlAlchemyDomainRepository(session)
    domain = domains.get_by_hostname(host)
    if domain is None:  # should exist (pre-created); create defensively
        domain = domains.create(Domain(hostname=host))
    observation = run_domain_observation(
        session,
        company_id=company_id,  # type: ignore[arg-type]
        domain_id=domain.id,
        idempotency_key=uuid4().hex,
        collector_version=get_settings().collector_version,
        dns_observer=DnsObserver(TIGHT),
        http_observer=HttpObserver(TIGHT),
    )
    run_feature_extraction(session, observation_id=observation.id, extractor=EXTRACTOR)
    snapshots = SqlAlchemyObservationFeatureRepository(session).list_by_domain(domain.id)
    return DomainFeatureView.from_snapshot(snapshots[-1], host) if snapshots else None


def _process(factory: object, task: dict[str, str]) -> dict[str, object]:
    out: dict[str, object] = {c: "" for c in COLUMNS}
    out.update(
        {
            "company_id": task["company_id"],
            "domain1_raw": task["domain1_raw"],
            "domain2_raw": task["domain2_raw"],
            "domain1": task["host_a"],
            "domain2": task["host_b"],
        }
    )
    try:
        with session_scope(factory) as session:  # type: ignore[arg-type]
            company = Company(
                external_company_id=f"fast-{task['company_id']}-{uuid4().hex[:6]}",
                name_raw=f"Batch {task['company_id']}",
                name_normalized=f"batch {task['company_id']}",
            )
            session.add(company)
            session.flush()
            view_a = _prepare(session, company.id, task["host_a"])
            view_b = _prepare(session, company.id, task["host_b"])
    except Exception as exc:  # noqa: BLE001 - record and continue
        out["note"] = f"error: {type(exc).__name__}: {exc}"
        return out
    if view_a is None or view_b is None:
        out["note"] = "no observation for one or both domains"
        return out
    match = MATCHER.match(view_a, view_b)
    out["same_organization"] = match.same_organization
    out["match_confidence"] = match.confidence
    out["match_reason_codes"] = ",".join(c.value for c in match.reason_codes)
    if match.same_organization:
        resolution = RESOLVER.resolve([view_a, view_b])
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
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--workers", type=int, default=20)
    args = parser.parse_args()

    workbook = openpyxl.load_workbook(args.input, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    raw_rows = list(sheet.iter_rows(values_only=True))[1:][args.start : args.start + args.limit]

    settings = get_settings()
    engine = create_engine(
        make_url(settings.require_database_url()),
        pool_pre_ping=True,
        pool_size=args.workers + 4,
        max_overflow=8,
    )
    factory: sessionmaker = create_session_factory(engine)

    tasks: list[dict[str, str]] = []
    invalid: list[dict[str, object]] = []
    hosts: set[str] = set()
    for raw in raw_rows:
        company_id = "" if raw[0] is None else str(raw[0]).replace(".0", "")
        raw1, raw2 = str(raw[1] or "").strip(), str(raw[2] or "").strip()
        try:
            host_a, host_b = normalize_domain(raw1), normalize_domain(raw2)
        except ValueError as exc:
            invalid.append(
                {
                    **{c: "" for c in COLUMNS},
                    "company_id": company_id,
                    "domain1_raw": raw1,
                    "domain2_raw": raw2,
                    "note": f"invalid domain: {exc}",
                }
            )
            continue
        if host_a == host_b:
            invalid.append(
                {
                    **{c: "" for c in COLUMNS},
                    "company_id": company_id,
                    "domain1_raw": raw1,
                    "domain2_raw": raw2,
                    "domain1": host_a,
                    "domain2": host_b,
                    "note": "same host after normalization",
                }
            )
            continue
        tasks.append(
            {
                "company_id": company_id,
                "domain1_raw": raw1,
                "domain2_raw": raw2,
                "host_a": host_a,
                "host_b": host_b,
            }
        )
        hosts.update({host_a, host_b})

    # Pre-create all domains once so parallel workers never race to insert them.
    with session_scope(factory) as session:
        repo = SqlAlchemyDomainRepository(session)
        for host in sorted(hosts):
            if repo.get_by_hostname(host) is None:
                repo.create(Domain(hostname=host))

    done = 0
    total = len(tasks)
    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in invalid:
            writer.writerow(row)
        handle.flush()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_process, factory, task): task for task in tasks}
            for future in as_completed(futures):
                result = future.result()
                writer.writerow(result)
                handle.flush()
                done += 1
                print(
                    f"({done}/{total}) {result['domain1_raw']} / {result['domain2_raw']} -> "
                    f"same_org={result['same_organization']} primary={result['primary_domain']}"
                )
    print(f"\nDone. Wrote {total + len(invalid)} rows to {args.output}")


if __name__ == "__main__":
    main()
