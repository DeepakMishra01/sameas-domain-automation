# Architecture

## System boundary

The API accepts CPT-supplied candidate domains through a future integration adapter. It does not assume a Tracxn API, authentication mechanism, topic, or internal schema.

## Target pipeline

`Input → normalization → safe collection → evidence extraction → feature extraction → organization resolution → primary-domain resolution → confidence/decision → human review/training data`

Collection produces facts; matching consumes normalized features; canonical resolution consumes only confirmed organization members. An optional `LLMVerifier` will receive structured evidence after deterministic processing and must return only schema-valid references to supplied evidence IDs.

## Current modules

- `apps/api`: HTTP transport only. It currently exposes `GET /health`.
- `domain_resolver/config`: typed environment configuration.
- `domain_resolver/normalization`: independently testable normalization utilities.
- `domain_resolver/models`: SQLAlchemy 2.x PostgreSQL persistence definitions.
- `domain_resolver/infrastructure`: explicit engine, session factory, transaction, and request-dependency utilities.
- `domain_resolver/repositories`: small persistence ports and thin SQLAlchemy adapters.
- `domain_resolver/observation`: Phase 3 safe domain observation — SSRF-resistant network layer, DNS and HTTP observers, bounded HTML extraction, and the observation orchestration service. It answers "what did we observe?" only; it performs no matching, scoring, or primary-domain selection. See [observation.md](observation.md).
- `domain_resolver/features`: Phase 4 deterministic evidence & feature extraction — normalization, taxonomy, a pure extractor, and the persistence service. It consumes persisted observations only and makes no matching or ownership judgement. See [feature-extraction.md](feature-extraction.md) and [evidence-taxonomy.md](evidence-taxonomy.md).
- `apps/worker`: Celery application with the `observe_domain` (Phase 3) and `extract_features` (Phase 4) tasks wrapping their services.
- `extractors`, `matching`, `decisions`, and `llm`: reserved boundaries for subsequent phases.

## Architectural decisions

1. Use SQLAlchemy 2.x declarative typed models and PostgreSQL-compatible types; migrations, rather than model import side effects, will own schema lifecycle.
2. Preserve source values alongside normalized values and append observations/evidence to retain historical change.
3. Keep application/domain logic outside FastAPI routes, and keep persistence details outside decision logic.
4. Make scoring/rule and model versions explicit fields. No initial numeric evidence weights are asserted as validated.
7. Evidence attribution is relational, not JSON-only: `decision_evidence` and `relationship_evidence` link tables make every material decision and relationship assessment traceable to specific evidence IDs under `RESTRICT` foreign keys. Evidence/reason codes are a reusable taxonomy, not unique row identifiers, so evidence remains append-only.
8. Relationship pairs are stored in a single canonical direction (enforced by a database check and by the repository), so an unordered pair never appears as two opposite-direction rows while historical assessments across model versions are still retained.
5. Crawling will be defensive by design: external URL validation, private-network blocking, rate limiting, retries, cache/idempotency, and classified errors are required before collection is introduced.
6. The health API never creates an engine. Database URLs are required at the point an engine or migration is requested, allowing configuration-free imports and liveness checks.
