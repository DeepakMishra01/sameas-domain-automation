#!/usr/bin/env python
"""Geographies Served: for each company, find the countries it serves and categorise.

For every company (one domain per row) this:
  1. opens the company website and reads its text + on-page addresses,
  2. runs a Google / Wikipedia search (Serper) for its locations,
  3. asks the LLM for the list of countries it operates in or serves,
  4. computes Single Geo / Multinational / IsGlobal from that list (in code),
  5. writes an Excel report (rows kept in input order).

Usage:
  python scripts/run_geoserved.py INPUT.xlsx OUTPUT.xlsx [--limit N] [--workers W]

INPUT.xlsx needs a company-name column and a domain column (found by header).
"""

from __future__ import annotations

import argparse
import csv
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from dataclasses import replace as _replace
from pathlib import Path
from uuid import uuid4

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from domain_resolver.config.dotenv import load_env_file
from domain_resolver.config.settings import get_settings
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.geo.category import categorize, country_count
from domain_resolver.geo.results import GeoVerdict
from domain_resolver.geo.verifier import GeoVerifier
from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.llm.client import build_client_from_env
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
from domain_resolver.search.serper import SerperClient, build_serper_from_env

COLUMNS = [
    "sno",
    "company_name",
    "domain",
    "countries_served",
    "country_count",
    "category",
    "headquarters",
    "confidence",
    "source",
    "evidence_quote",
    "reasoning",
    "note",
]

TIGHT = _replace(
    DEFAULT_LIMITS,
    connect_timeout=3.0,
    read_timeout=6.0,
    write_timeout=3.0,
    pool_timeout=3.0,
    total_timeout=12.0,
)
EXTRACTOR = FeatureExtractor(get_settings().feature_extractor_version)


def _columns(header: tuple) -> dict[str, int]:
    idx = {}
    for i, cell in enumerate(header):
        if cell is None:
            continue
        t = str(cell).strip().lower()
        if "domain" in t or "url" in t or "website" in t:
            idx.setdefault("domain", i)
        elif "company" in t or t == "name" or "name" in t:
            idx.setdefault("company", i)
        elif t in {"sno", "sno.", "s.no", "s no", "sr", "sr no"} or "s.no" in t:
            idx.setdefault("sno", i)
    idx.setdefault("sno", 0)
    idx.setdefault("company", 1)
    idx.setdefault("domain", 2)
    return idx


@dataclass
class _Config:
    verifier: GeoVerifier
    serper: SerperClient | None
    min_conf: float
    serp_cache: dict[str, str]
    stats: dict[str, int]
    cache_lock: threading.Lock


def _observe(session: object, company_id: object, host: str) -> DomainFeatureView | None:
    domains = SqlAlchemyDomainRepository(session)
    domain = domains.get_by_hostname(host)
    if domain is None:
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
    snaps = SqlAlchemyObservationFeatureRepository(session).list_by_domain(domain.id)
    return DomainFeatureView.from_snapshot(snaps[-1], host) if snaps else None


def _resolved(v: GeoVerdict | None, min_conf: float) -> bool:
    """A verdict is good enough to stop escalating: has HQ + >=1 country, confident."""
    return v is not None and bool(v.headquarters) and bool(v.countries) and v.confidence >= min_conf


def _score(v: GeoVerdict | None, min_conf: float) -> tuple[int, int, float]:
    if v is None:
        return (0, 0, 0.0)
    return (1 if _resolved(v, min_conf) else 0, len(v.countries), v.confidence)


def _best(a: GeoVerdict | None, b: GeoVerdict | None, min_conf: float) -> GeoVerdict | None:
    """Pick the stronger verdict (resolved > more countries > higher confidence)."""
    return a if _score(a, min_conf) >= _score(b, min_conf) else b


def _cached_search(cfg: _Config, query: str) -> str:
    """One Serper search, cached by query. Counts only real (cache-miss) calls."""
    if cfg.serper is None:
        return ""
    with cfg.cache_lock:
        if query in cfg.serp_cache:
            return cfg.serp_cache[query]
    res = cfg.serper.search(query)
    with cfg.cache_lock:
        cfg.serp_cache.setdefault(query, res)
        cfg.stats["searches"] = cfg.stats.get("searches", 0) + 1
    return res


def _looks_multinational(v: GeoVerdict | None) -> bool:
    return v is not None and len(v.countries) >= 2


def _geo_verdict(cfg: _Config, view: DomainFeatureView, company: str, host: str) -> tuple:
    """Escalation ladder: website first, then search only when needed.

    Returns (verdict, source). Keeps Serper cheap: a company that resolves from its
    own website costs 0 searches; one combined search handles most of the rest;
    multinational or still-thin companies escalate to LinkedIn + Wikipedia + a
    worldwide-operations query to build the FULL country list.
    """
    label = company or host

    def reverify(parts: list[str]) -> GeoVerdict | None:
        return cfg.verifier.verify(view, company, "\n\n".join(p for p in parts if p))

    verdict = cfg.verifier.verify(view, company, "")
    source = "website"
    if cfg.serper is None:
        return verdict, source

    # Tier 1: one combined search, unless the website already resolved a single geo.
    if not _resolved(verdict, cfg.min_conf) or _looks_multinational(verdict):
        parts = [_cached_search(cfg, f"{label} {host} headquarters locations countries served")]
        verdict = _best(verdict, reverify(parts), cfg.min_conf)
        source = "website + 1 search"
        # Tier 2: escalate for multinationals or still-thin results -> fuller list.
        if not _resolved(verdict, cfg.min_conf) or _looks_multinational(verdict):
            parts.append(
                _cached_search(cfg, f"{label} linkedin headquarters OR locations OR offices")
            )
            parts.append(
                _cached_search(cfg, f"{label} wikipedia headquarters countries operations")
            )
            parts.append(
                _cached_search(
                    cfg,
                    f'{label} {host} "countries" OR "global presence" '
                    f'OR "operations in" OR "offices" worldwide',
                )
            )
            verdict = _best(verdict, reverify(parts), cfg.min_conf)
            source = "website + searches"
    return verdict, source


def _process(factory: object, row: dict[str, str], cfg: _Config) -> dict[str, str]:
    out: dict[str, str] = {c: "" for c in COLUMNS}
    out["sno"] = row["sno"]
    out["company_name"] = row["company_name"]
    raw_domain = row["domain_raw"]
    try:
        host = normalize_domain(raw_domain)
    except ValueError as exc:
        out["domain"] = raw_domain
        out["category"] = "Unknown"
        out["note"] = f"invalid domain: {exc}"
        return out
    out["domain"] = host
    try:
        with session_scope(factory) as session:  # type: ignore[arg-type]
            company = Company(
                external_company_id=f"geo-{row['sno']}-{uuid4().hex[:6]}",
                name_raw=row["company_name"] or host,
                name_normalized=(row["company_name"] or host).lower(),
            )
            session.add(company)
            session.flush()
            view = _observe(session, company.id, host)
            if view is None:
                out["category"] = "Unknown"
                out["note"] = "no observation (site did not load)"
                return out
            verdict, source = _geo_verdict(cfg, view, row["company_name"], host)
    except Exception as exc:  # noqa: BLE001 - record and continue
        out["category"] = "Unknown"
        out["note"] = f"error: {type(exc).__name__}: {exc}"
        return out
    if verdict is None:
        out["category"] = "Unknown"
        out["note"] = "needs review (no AI verdict)"
        return out
    out["countries_served"] = ", ".join(verdict.countries)
    out["country_count"] = str(country_count(verdict.countries))
    out["category"] = categorize(verdict.countries)
    out["headquarters"] = verdict.headquarters or ""
    out["confidence"] = str(verdict.confidence)
    out["source"] = source
    out["evidence_quote"] = verdict.evidence_quote
    out["reasoning"] = verdict.reasoning
    return out


CAT_COLORS = {
    "Single Geo": "FFF2CC",
    "Multinational": "DDEBF7",
    "IsGlobal": "E2EFDA",
    "Unknown": "F2F2F2",
}


def _write_excel(rows: list[dict[str, str]], path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Geographies Served"
    ws.append([c.replace("_", " ").title() for c in COLUMNS])
    for i in range(1, len(COLUMNS) + 1):
        cell = ws.cell(1, i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
    cat_col = COLUMNS.index("category") + 1
    for r in rows:
        ws.append([r.get(c, "") for c in COLUMNS])
        colour = CAT_COLORS.get(r.get("category", ""))
        if colour:
            ws.cell(ws.max_row, cat_col).fill = PatternFill("solid", fgColor=colour)
    widths = {
        "company_name": 26,
        "domain": 26,
        "countries_served": 50,
        "category": 15,
        "headquarters": 18,
        "evidence_quote": 45,
        "reasoning": 50,
        "note": 26,
    }
    for i, c in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(c, 12)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="Find geographies served per company.")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--limit", type=int, default=100000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.input, read_only=True, data_only=True)
    raw = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))
    col = _columns(raw[0]) if raw else {"sno": 0, "company": 1, "domain": 2}
    tasks: list[dict[str, str]] = []
    for r in raw[1:][: args.limit]:
        tasks.append(
            {
                "sno": (
                    ""
                    if len(r) <= col["sno"] or r[col["sno"]] is None
                    else str(r[col["sno"]]).replace(".0", "")
                ),
                "company_name": (
                    ""
                    if len(r) <= col["company"] or r[col["company"]] is None
                    else str(r[col["company"]]).strip()
                ),
                "domain_raw": (
                    ""
                    if len(r) <= col["domain"] or r[col["domain"]] is None
                    else str(r[col["domain"]]).strip()
                ),
            }
        )

    serper = build_serper_from_env()
    cfg = _Config(
        verifier=GeoVerifier(build_client_from_env()),
        serper=serper,
        min_conf=float(os.environ.get("DERE_GEO_MIN_CONF", "0.6")),
        serp_cache={},
        stats={"searches": 0},
        cache_lock=threading.Lock(),
    )
    engine = create_engine(
        make_url(get_settings().require_database_url()),
        pool_pre_ping=True,
        pool_size=args.workers + 4,
        max_overflow=8,
    )
    factory = create_session_factory(engine)

    results: dict[int, dict[str, str]] = {}
    total = len(tasks)
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process, factory, t, cfg): i for i, t in enumerate(tasks)}
        for fut in as_completed(futures):
            i = futures[fut]
            results[i] = fut.result()
            done += 1
            r = results[i]
            cc = r.get("country_count") or "-"
            print(f"({done}/{total}) {r['domain']} -> {r['category']} [{cc}]")

    ordered = [results[i] for i in range(total)]
    out_csv = str(Path(args.output).with_suffix("")) + ".csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)
    _write_excel(ordered, args.output)

    from collections import Counter

    cats = Counter(r["category"] for r in ordered)
    searches = cfg.stats.get("searches", 0)
    per = searches / total if total else 0
    print(f"\nCategories: {dict(cats)}")
    print(f"Serper searches used: {searches}  ({per:.2f} per company)")
    if serper is None:
        print("(Serper off - set DERE_SERPER_API_KEY for Google/Wikipedia evidence.)")
    print(f"Wrote -> {args.output}  (and {out_csv})")


if __name__ == "__main__":
    main()
