# Product requirements

## Objective

DERE receives a company identifier, company name, and candidate domains already discovered by CPT. It must retain source provenance and ultimately determine organization membership, primary/secondary domains, unrelated domains, review cases, confidence, and traceable evidence.

## Decision boundaries

Organization membership and primary-domain selection are separate decisions. A primary-domain signal may be evaluated only after membership is established; it is not proof of membership by itself.

## Required outcomes

- Preserve immutable historical observations and evidence.
- Return a domain-level state: `PRIMARY`, `SECONDARY`, `UNRELATED`, `REVIEW_REQUIRED`, `UNKNOWN`, `DEAD`, `PARKED`, or `REDIRECT`.
- Return an overall decision: `AUTO_ACCEPT`, `AUTO_REJECT`, or `REVIEW_REQUIRED`.
- Link every material decision to evidence IDs, reason codes, a score/rule version, and model version (`dere-v1` initially).
- Capture human corrections for later evaluation and training.

## Completed foundation scope

Phase 0/1 established contracts, configuration, persistence boundaries, domain normalization, and a health API. Phase 2 adds Alembic-managed PostgreSQL schema, transaction infrastructure, repository ports/adapters, and CPT gold-label test fixtures. No crawler, resolver, decision engine, LLM, Tracxn integration, or external paid API is implemented.

## Assumptions

- Candidate domains are supplied by a future CPT adapter; their discovery source is optional and retained as provenance.
- PostgreSQL is the system of record and Redis/Celery are future processing infrastructure.
- Configuration is supplied via environment variables and secrets are never committed.
- Historical facts are appended as observations/evidence rather than overwritten.
