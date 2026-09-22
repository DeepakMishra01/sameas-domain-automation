#!/usr/bin/env python
"""AI-verify the UNCERTAIN relationship pairs, keeping solid ones deterministic.

Reads a classify_relationships CSV. For each row that is low-confidence/assumed,
brand-identity, or review (the ~uncertain subset), it asks the configured LLM
(Ollama/Qwen by default, free & local; Gemini optional) to decide the relationship
from the ALREADY-STORED page facts (no re-crawl). Evidence-backed deterministic
rows (redirect, same-name, canonical, explicit text) are left untouched.

Adds columns: decision_source, ai_confidence, ai_evidence_quote, ai_reasoning.

Usage:
  DERE_DATABASE_URL=... [DERE_LLM_PROVIDER=ollama DERE_LLM_MODEL=qwen2.5:14b-instruct] \\
    python scripts/ai_verify.py RESULTS.csv OUTPUT.csv [--limit N]
"""

from __future__ import annotations

import argparse
import csv

from domain_resolver.config.settings import get_settings
from domain_resolver.features.results import FeatureSet
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)
from domain_resolver.llm.client import build_client_from_env
from domain_resolver.llm.verifier import LlmRelationshipVerifier
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDomainRepository,
    SqlAlchemyObservationFeatureRepository,
)

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
}
EXTRA = ["decision_source", "ai_confidence", "ai_evidence_quote", "ai_reasoning"]


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--limit", type=int, default=100000)
    args = parser.parse_args()

    with open(args.input, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))[: args.limit]
    fieldnames = list(rows[0].keys()) + [c for c in EXTRA if c not in rows[0]] if rows else []

    verifier = LlmRelationshipVerifier(build_client_from_env())
    factory = create_session_factory(create_engine_from_settings(get_settings()))

    verified = kept = failed = 0
    with (
        open(args.output, "w", newline="", encoding="utf-8") as handle,
        session_scope(factory) as session,
    ):
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            for col in EXTRA:
                row.setdefault(col, "")
            if not row.get("domain1") or not row.get("domain2") or not _needs_ai(row):
                row["decision_source"] = "DETERMINISTIC"
                writer.writerow(row)
                kept += 1
                continue
            va, vb = _view(session, row["domain1"]), _view(session, row["domain2"])
            verdict = verifier.verify(va, vb, row.get("explanation", "")) if va and vb else None
            if verdict is None:
                row["decision_source"] = "DETERMINISTIC (AI unavailable)"
                failed += 1
            else:
                row["relationship_type"] = verdict.relationship_type.value
                row["relationship_subtype"] = (
                    verdict.relationship_subtype.value if verdict.relationship_subtype else ""
                )
                if verdict.primary_domain:
                    row["primary_domain"] = verdict.primary_domain
                if verdict.secondary_domain:
                    row["secondary_domain"] = verdict.secondary_domain
                row["confidence"] = verdict.confidence
                row["reason_codes"] = "AI_VERIFIED"
                row["explanation"] = verdict.reasoning
                row["decision_source"] = "AI"
                row["ai_confidence"] = verdict.confidence
                row["ai_evidence_quote"] = verdict.evidence_quote
                row["ai_reasoning"] = verdict.reasoning
                verified += 1
            writer.writerow(row)
            print(
                f"[{va and 'ok' or 'no-obs'}] {row['domain1']} / {row['domain2']} -> "
                f"{row['relationship_type']} ({row['decision_source']})"
            )
    print(f"\nDeterministic kept: {kept} | AI-verified: {verified} | AI unavailable: {failed}")
    print(f"Wrote -> {args.output}")


if __name__ == "__main__":
    main()
