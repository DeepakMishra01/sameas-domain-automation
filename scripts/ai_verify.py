#!/usr/bin/env python
"""AI-verify the UNCERTAIN relationship pairs, keeping solid ones deterministic.

Reads a classify_relationships CSV. For each row that is low-confidence/assumed,
brand-identity, or review (the ~uncertain subset), it asks the configured LLM
(Ollama/Qwen by default, free & local; Gemini optional) to decide the relationship
from the ALREADY-STORED page facts (no re-crawl). Evidence-backed deterministic
rows (redirect, same-name, canonical, explicit text) are left untouched.

Adds columns: decision_source, qc_agree, ai_confidence, ai_evidence_quote,
ai_reasoning.

Layers:
  1. deterministic (already in the input CSV)
  2. AI verification of the uncertain rows
  3. Serper web QC — low-confidence only by default, or EVERY pair when
     DERE_SERP_ALL=1. In QC-on-all mode, agreement confirms the verdict and a
     disagreement routes the pair to REVIEW_REQUIRED (a proven redirect is kept).

Runs pairs in parallel (network-bound work); tune with --workers (default 4).

Usage:
  DERE_DATABASE_URL=... [DERE_LLM_PROVIDER=ollama DERE_LLM_MODEL=qwen2.5:14b-instruct] \\
    [DERE_SERP_ALL=1] python scripts/ai_verify.py RESULTS.csv OUTPUT.csv [--limit N] [--workers W]
"""

from __future__ import annotations

import argparse
import csv
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from domain_resolver.classification.relationship_types import RelationshipType
from domain_resolver.config.dotenv import load_env_file
from domain_resolver.config.settings import get_settings
from domain_resolver.features.results import FeatureSet
from domain_resolver.infrastructure.database import (
    create_session_factory,
    session_scope,
)
from domain_resolver.llm.client import build_client_from_env
from domain_resolver.llm.results import AiVerdict
from domain_resolver.llm.verifier import LlmRelationshipVerifier
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDomainRepository,
    SqlAlchemyObservationFeatureRepository,
)
from domain_resolver.search.query import build_relationship_queries
from domain_resolver.search.serper import SerperClient, build_serper_from_env

# Deterministic reason codes that are trustworthy -> never sent to the LLM.
SOLID_CODES = {
    "REDIRECT_TO_PRIMARY",
    "REDIRECT_CHAIN_TO_PRIMARY",
    "COMMON_REDIRECT_TARGET",
    "SAME_NAME_DIFFERENT_TLD",
    "BRAND_PREFIX_VARIANT",
    "CANONICAL_TO_PARENT",
    "PRODUCT_OF",
    "BRAND_OF",
    "SUBSIDIARY_OF",
    "BUSINESS_UNIT_OF",
    "SERVICE_OF",
    "DIVISION_OF",
    "REGIONAL_ENTITY_OF",
    "PART_OF_STATEMENT",
    "ACQUIRED_BY",
    "ACQUISITION_ANNOUNCEMENT",
    # Parked / for-sale / broker / host placeholder -> deterministic UNRELATED.
    # Kept out of the LLM: the shared host/broker content reliably fools the model
    # into calling these PART_OF, so trust the deterministic guard instead.
    "PARKED_OR_HOSTING_PAGE",
}
EXTRA = ["decision_source", "ai_confidence", "ai_evidence_quote", "ai_reasoning", "qc_agree"]

# Deterministic codes that are proven FACTS (an observed redirect). A web QC may
# disagree, but a redirect is authoritative and must not be overwritten by it.
_PROVEN_CODES = {
    "REDIRECT_TO_PRIMARY",
    "REDIRECT_CHAIN_TO_PRIMARY",
    "COMMON_REDIRECT_TARGET",
}


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


def _needs_ai(row: dict[str, str]) -> bool:
    first_code = (row.get("reason_codes") or "").split(",")[0]
    return first_code not in SOLID_CODES  # assumed / brand-identity / review / blank


def _web_evidence(
    serper: SerperClient,
    view_a: DomainFeatureView,
    view_b: DomainFeatureView,
    max_queries: int,
    cache: dict[str, str],
    lock: threading.Lock,
) -> str:
    """Run the (cached) Serper queries for a pair and return a combined evidence block.

    Queries are built from the domains' entity names (not raw hostnames) and cover
    the relationship + identity/knowledge-graph angles. Results are cached by query
    string (guarded by ``lock`` for concurrent workers) so duplicate pairs and
    re-runs never pay for the same search twice.
    """
    blocks: list[str] = []
    for query in build_relationship_queries(view_a, view_b, max_queries=max_queries):
        with lock:
            hit = query in cache
            result = cache.get(query, "")
        if not hit:
            result = serper.search(query)
            with lock:
                cache[query] = result
        if result:
            blocks.append(f"[search: {query}]\n{result}")
    return "\n\n".join(blocks)


def _apply_verdict(
    row: dict[str, str], verdict: AiVerdict, *, source: str, reason_code: str
) -> None:
    """Write an AiVerdict's fields onto the output row.

    Sector gate: an AI SAME_AS is only reachable without a redirect (redirects are
    solid and never sent to the LLM). If the model judged the two domains to be in
    different sectors (``same_sector is False``), they cannot be the same company,
    so the SAME_AS is refused and the pair is flagged for review instead.
    """
    if verdict.relationship_type is RelationshipType.SAME_AS and verdict.same_sector is False:
        row["relationship_type"] = "REVIEW_REQUIRED"
        row["relationship_subtype"] = ""
        row["confidence"] = str(verdict.confidence)
        row["reason_codes"] = "SECTOR_MISMATCH_NOT_SAMEAS"
        row["explanation"] = (
            "AI judged SAME_AS but the two domains are in different sectors; different "
            f"sectors cannot be the same company, so flagged for review. {verdict.reasoning}"
        )
        row["decision_source"] = f"{source} (sector gate)"
        row["ai_confidence"] = str(verdict.confidence)
        row["ai_evidence_quote"] = verdict.evidence_quote
        row["ai_reasoning"] = verdict.reasoning
        return
    row["relationship_type"] = verdict.relationship_type.value
    row["relationship_subtype"] = (
        verdict.relationship_subtype.value if verdict.relationship_subtype else ""
    )
    if verdict.primary_domain:
        row["primary_domain"] = verdict.primary_domain
    if verdict.secondary_domain:
        row["secondary_domain"] = verdict.secondary_domain
    row["confidence"] = str(verdict.confidence)
    row["reason_codes"] = reason_code
    row["explanation"] = verdict.reasoning
    row["decision_source"] = source
    row["ai_confidence"] = str(verdict.confidence)
    row["ai_evidence_quote"] = verdict.evidence_quote
    row["ai_reasoning"] = verdict.reasoning


# Columns copied from a cached AI verdict when resuming.
_AI_FIELDS = (
    "relationship_type",
    "relationship_subtype",
    "primary_domain",
    "secondary_domain",
    "confidence",
    "reason_codes",
    "explanation",
    "ai_confidence",
    "ai_evidence_quote",
    "ai_reasoning",
)


def _load_prior_ai(path: str) -> dict[tuple[str, str], dict[str, str]]:
    """Load already-AI-decided pairs from a previous (possibly interrupted) output.

    Lets a re-run resume: pairs already decided by the AI are reused instead of
    re-calling the model (saves time and cost, and survives Ctrl+C / rate limits).
    """
    prior: dict[tuple[str, str], dict[str, str]] = {}
    if not os.path.isfile(path):
        return prior
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row.get("decision_source") or "").startswith("AI") and row.get("domain1"):
                    prior[(row["domain1"], row["domain2"])] = row
    except (OSError, csv.Error):
        pass
    return prior


@dataclass
class _Config:
    """Shared, read-mostly settings passed to every worker thread."""

    verifier: LlmRelationshipVerifier
    serper: SerperClient | None
    serp_min: float
    serp_queries: int
    serp_all: bool
    qc_correct_min: float
    prior: dict[tuple[str, str], dict[str, str]]
    serp_cache: dict[str, str]
    cache_lock: threading.Lock


def _process_row(
    factory: object, row: dict[str, str], cfg: _Config
) -> tuple[dict[str, str], list[str]]:
    """Classify one pair (AI + optional Serper QC). Returns (row, counter-keys).

    Self-contained and thread-safe: opens its own DB session, shares only the
    read-mostly config and the lock-guarded Serper cache. All counters are returned
    as keys for the caller to aggregate (no shared mutable counters).
    """
    keys: list[str] = []
    for col in EXTRA:
        row.setdefault(col, "")
    d1, d2 = row.get("domain1"), row.get("domain2")
    if not d1 or not d2:
        row["decision_source"] = "DETERMINISTIC"
        return row, ["kept"]
    needs_ai = _needs_ai(row)
    sector = row.get("feed_sector", "")  # Domain-1 sector, gates non-redirect SAME_AS

    with session_scope(factory) as session:  # type: ignore[arg-type]
        # ---- QC-on-all mode: cross-check every pair with a Serper web search -----
        if cfg.serp_all:
            proven = (row.get("reason_codes") or "").split(",")[0] in _PROVEN_CODES
            va, vb = _view(session, d1), _view(session, d2)
            hint = row.get("explanation", "")
            # Base verdict: AI for uncertain rows, deterministic for solid ones.
            if needs_ai and va and vb:
                base = cfg.verifier.verify(va, vb, hint, domain_a_sector=sector)
                if base is not None:
                    _apply_verdict(row, base, source="AI", reason_code="AI_VERIFIED")
                    keys.append("verified")
                else:
                    row["decision_source"] = "DETERMINISTIC (AI unavailable)"
                    keys.append("failed")
            else:
                row["decision_source"] = "DETERMINISTIC"
            base_type = row["relationship_type"]
            base_reason = row.get("reason_codes") or ""
            # QC layer: Google-search the pair and re-decide with web evidence.
            qc = None
            if cfg.serper is not None and va and vb:
                web = _web_evidence(
                    cfg.serper, va, vb, cfg.serp_queries, cfg.serp_cache, cfg.cache_lock
                )
                if web:
                    keys.append("searched")
                    qc = cfg.verifier.verify(va, vb, hint, web_evidence=web, domain_a_sector=sector)
            if qc is None:
                row["qc_agree"] = "no-evidence"
                keys.append("qc_noevidence")
            elif qc.relationship_type.value == base_type:
                row["qc_agree"] = "yes"
                row["ai_confidence"] = str(qc.confidence)
                row["ai_evidence_quote"] = qc.evidence_quote
                row["ai_reasoning"] = qc.reasoning
                row["reason_codes"] = f"{base_reason},SERP_QC_CONFIRMED".strip(",")
                row["decision_source"] = row["decision_source"].split(" (")[0] + "+SERP-QC"
                keys.append("qc_confirmed")
            elif proven:
                # Redirect is a fact; keep it but record the disagreement.
                row["qc_agree"] = "no (redirect kept)"
                row["ai_reasoning"] = qc.reasoning
                row["decision_source"] += " (QC differs)"
                keys.append("qc_conflict")
            elif not needs_ai:
                # A documented deterministic rule (e.g. same-name-different-TLD,
                # canonical-to-parent, explicit "part of"/acquisition text). QC may
                # NOT silently override the SOP rule; a disagreement is surfaced for a
                # human instead of trusting the model over the documented rule.
                row["qc_agree"] = "no (rule protected -> review)"
                row["ai_confidence"] = str(qc.confidence)
                row["ai_evidence_quote"] = qc.evidence_quote
                row["ai_reasoning"] = qc.reasoning
                row["relationship_type"] = "REVIEW_REQUIRED"
                row["relationship_subtype"] = ""
                row["reason_codes"] = "SERP_QC_CONFLICT"
                row["decision_source"] = "SERP-QC vs RULE -> REVIEW"
                row["explanation"] = (
                    f"Documented rule ({base_reason.split(',')[0]}) said {base_type}, "
                    f"web QC said {qc.relationship_type.value} (confidence "
                    f"{qc.confidence:.2f}). Rule protected; needs manual review. "
                    f"QC evidence: {qc.reasoning}"
                )
                keys.append("qc_conflict")
            elif qc.confidence >= cfg.qc_correct_min:
                # Confident QC disagreement -> adopt the QC's category (it saw web
                # evidence the base verdict did not). Records the override.
                row["qc_agree"] = "no (QC corrected)"
                _apply_verdict(row, qc, source="SERP-QC CORRECTED", reason_code="SERP_QC_CORRECTED")
                row["explanation"] = (
                    f"QC corrected {base_type} -> {qc.relationship_type.value} "
                    f"(confidence {qc.confidence:.2f}). {qc.reasoning}"
                )
                keys.append("qc_corrected")
            else:
                # Low-confidence disagreement -> genuine conflict; a human decides.
                row["qc_agree"] = "no (low-confidence -> review)"
                row["ai_confidence"] = str(qc.confidence)
                row["ai_evidence_quote"] = qc.evidence_quote
                row["ai_reasoning"] = qc.reasoning
                row["relationship_type"] = "REVIEW_REQUIRED"
                row["relationship_subtype"] = ""
                row["reason_codes"] = "SERP_QC_CONFLICT"
                row["decision_source"] = "SERP-QC CONFLICT -> REVIEW"
                row["explanation"] = (
                    f"Layers disagree: base said {base_type}, web QC said "
                    f"{qc.relationship_type.value} (confidence {qc.confidence:.2f}, below "
                    f"the {cfg.qc_correct_min:.2f} correction threshold). Needs manual review. "
                    f"QC evidence: {qc.reasoning}"
                )
                keys.append("qc_conflict")
            return row, keys

        # ---- default mode: keep solid rows; AI (+ low-confidence search) else -----
        if not needs_ai:
            row["decision_source"] = "DETERMINISTIC"
            return row, ["kept"]
        cached_row = cfg.prior.get((d1, d2))
        if cached_row is not None:
            try:
                prior_conf = float(cached_row.get("ai_confidence") or 0.0)
            except ValueError:
                prior_conf = 0.0
            already_searched = cached_row.get("decision_source") == "AI+SEARCH"
            # Reuse confident verdicts. But if search is enabled and this cached verdict
            # was low-confidence (and not already search-assisted), re-verify it.
            reuse = not (
                cfg.serper is not None and prior_conf < cfg.serp_min and not already_searched
            )
            if reuse:
                for field in _AI_FIELDS:
                    if cached_row.get(field):
                        row[field] = cached_row[field]
                row["decision_source"] = "AI (cached)"
                return row, ["cached"]
        va, vb = _view(session, d1), _view(session, d2)
        hint = row.get("explanation", "")
        verdict = cfg.verifier.verify(va, vb, hint, domain_a_sector=sector) if va and vb else None
        used_search = False
        # Low-confidence (or failed) -> Google-search the pair and re-decide.
        if (
            va
            and vb
            and cfg.serper is not None
            and (verdict is None or verdict.confidence < cfg.serp_min)
        ):
            web = _web_evidence(
                cfg.serper, va, vb, cfg.serp_queries, cfg.serp_cache, cfg.cache_lock
            )
            if web:
                v2 = cfg.verifier.verify(va, vb, hint, web_evidence=web, domain_a_sector=sector)
                if v2 is not None and (verdict is None or v2.confidence >= verdict.confidence):
                    verdict, used_search = v2, True
        if verdict is None:
            row["decision_source"] = "DETERMINISTIC (AI unavailable)"
            keys.append("failed")
        else:
            _apply_verdict(
                row,
                verdict,
                source="AI+SEARCH" if used_search else "AI",
                reason_code="AI_SEARCH_VERIFIED" if used_search else "AI_VERIFIED",
            )
            keys.append("verified")
            if used_search:
                keys.append("searched")
        return row, keys


def main() -> None:
    load_env_file()  # pick up DB URL + LLM provider/model/key from .env if present
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--limit", type=int, default=100000)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel worker threads. Throughput is capped by the LLM/Serper API "
        "requests-per-minute limit, not CPU: on a free tier keep this low (2-4); "
        "raise it only with a higher API tier or multiple rotating keys.",
    )
    parser.add_argument(
        "--no-resume", action="store_true", help="ignore any existing output and redo every pair"
    )
    parser.add_argument(
        "--keep-order",
        action="store_true",
        help="write output rows in the same order as the input (default: completion order)",
    )
    args = parser.parse_args()

    with open(args.input, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))[: args.limit]
    fieldnames = list(rows[0].keys()) + [c for c in EXTRA if c not in rows[0]] if rows else []

    # DERE_SERP_ALL=1 -> run a Serper web QC on EVERY pair (not only low-confidence
    # ones): a third layer that cross-checks every output. Agreement confirms the
    # verdict. On disagreement (solid rules are protected):
    #   * proven redirect -> kept (authoritative fact);
    #   * other documented deterministic rule -> REVIEW_REQUIRED (QC may not override
    #     the SOP; a human decides);
    #   * uncertain verdict (assumed / brand-identity / AI) -> a CONFIDENT QC verdict
    #     (>= DERE_SERP_QC_CORRECT_MIN) corrects it, else REVIEW_REQUIRED.
    serper = build_serper_from_env()
    cfg = _Config(
        verifier=LlmRelationshipVerifier(build_client_from_env()),
        serper=serper,
        serp_min=float(os.environ.get("DERE_SERP_MIN_CONFIDENCE", "0.5")),
        serp_queries=max(1, int(os.environ.get("DERE_SERP_QUERIES", "2"))),
        serp_all=os.environ.get("DERE_SERP_ALL", "").strip().lower() in {"1", "true", "yes", "on"},
        qc_correct_min=float(os.environ.get("DERE_SERP_QC_CORRECT_MIN", "0.8")),
        prior={} if args.no_resume else _load_prior_ai(args.output),
        serp_cache={},
        cache_lock=threading.Lock(),
    )
    # Pooled engine so parallel workers each get their own connection.
    engine = create_engine(
        make_url(get_settings().require_database_url()),
        pool_pre_ping=True,
        pool_size=args.workers + 4,
        max_overflow=8,
    )
    factory = create_session_factory(engine)

    counts: Counter[str] = Counter()
    total = len(rows)
    done = 0
    # Pairs run in parallel (network-bound: LLM + Serper). The main thread does all
    # CSV writing and counting, so no writer lock is needed.
    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        buffer: dict[int, dict[str, str]] = {}  # only used when --keep-order
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_process_row, factory, row, cfg): i for i, row in enumerate(rows)
            }
            for future in as_completed(futures):
                idx = futures[future]
                out_row, keys = future.result()
                counts.update(keys)
                done += 1
                print(
                    f"({done}/{total}) {out_row.get('domain1')} / {out_row.get('domain2')} -> "
                    f"{out_row.get('relationship_type')} ({out_row.get('decision_source')})"
                )
                if args.keep_order:
                    buffer[idx] = out_row
                else:
                    writer.writerow(out_row)
                    handle.flush()
        if args.keep_order:  # emit in input order once every pair is done
            for i in range(len(rows)):
                writer.writerow(buffer[i])
            handle.flush()
    if cfg.serp_all:
        print(
            f"\nQC-on-all: AI-verified {counts['verified']} | searched {counts['searched']} | "
            f"QC confirmed {counts['qc_confirmed']} | QC corrected {counts['qc_corrected']} | "
            f"QC conflict->review {counts['qc_conflict']} | "
            f"no web evidence {counts['qc_noevidence']} | AI unavailable {counts['failed']}"
        )
    else:
        print(
            f"\nDeterministic kept: {counts['kept']} | AI-verified: {counts['verified']} "
            f"(of which web-search-assisted: {counts['searched']}) | "
            f"AI reused (cached): {counts['cached']} | AI unavailable: {counts['failed']}"
        )
    if serper is None:
        print("(Serper web-search fallback OFF — set DERE_SERPER_API_KEY to enable.)")
    print(f"Wrote -> {args.output}")


if __name__ == "__main__":
    main()
