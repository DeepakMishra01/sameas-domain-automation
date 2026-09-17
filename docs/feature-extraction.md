# Phase 4 — Evidence & feature extraction

Phase 4 turns persisted Phase 3 observations into deterministic, normalized,
versioned, auditable **features** and factual **evidence** that a future
matching engine (Phase 5) can consume. It makes no organization judgement.

```
RAW OBSERVATION  →  FACTUAL EVIDENCE  →  NORMALIZED FEATURES  →  [Phase 5 matching]
     (Phase 3)              (Phase 4)            (Phase 4)
```

## Purpose and non-goals

Phase 4 answers only *"what factual, normalized signals does this observation
contain?"*. It does **not**: match domains, score similarity, select
primary/secondary domains, classify PRIMARY/SECONDARY/UNRELATED, produce
decisions, call an LLM, use embeddings, apply probabilistic thresholds, or make
any business judgement.

## Inputs and outputs

- **Input:** a persisted `domain_observations` row (its `payload` is a Phase 3
  `ObservationResult`). No URLs are fetched and no DNS is resolved.
- **Output:** one append-only `observation_features` snapshot (versioned) plus a
  set of factual `evidence` rows, all traceable to the observation.

## Normalization rules

Pure, reproducible functions (`domain_resolver/features/normalization.py`):

- **Domain:** lowercase, IDNA, strip scheme/port/`www.`/trailing dot (shared
  normalizer).
- **URL:** require http(s) + host; lowercase scheme/host; drop default port and
  fragment; empty path → `/`; preserve path and query; reject malformed.
- **Text:** Unicode NFKC, lowercase, collapse whitespace; raw value preserved on
  the evidence row.
- **Email:** validate; lowercase the domain; preserve the local part; separate
  address from domain.
- **Phone:** strip to an optional leading `+` and digits; preserve a country code
  when present; never invent one; reject < 7 digits.
- **Social URL:** recognize known platforms; normalize to https + host + path;
  drop query/fragment. Recognizing a platform never claims two profiles are the
  same entity.
- **Tokenize / fingerprint:** bounded alphanumeric tokens and a stable SHA-256
  fingerprint of normalized text (deterministic; no embeddings, no similarity).

## Feature schema

`FeatureSet` (Pydantic, `feature_version`-stamped) includes: `normalized_domain`,
`final_domain`, `has_redirect`, `has_canonical`, `redirect_target_domain`,
`canonical_url`/`canonical_domain`, `normalized_title`,
`normalized_meta_description`, `normalized_text_excerpt`, `content_hash`,
`text_fingerprint`, `text_tokens`, `referenced_domains`,
`cross_domain_references`, `social_domains`/`social_profiles`,
`email_addresses`/`email_domains`, `phone_numbers`, `addresses` (empty; future),
and `dns_a/aaaa/cname/mx/ns`. Lists are deduped and sorted for reproducibility.

## Feature versioning

The extractor version identifies both the schema and the extraction logic. A new
version produces a new snapshot that coexists with older ones; historical
snapshots and evidence are never overwritten.

## Provenance

Every evidence row records: `observation_id` (FK), `domain_a_id` (observed
domain), `source` (extractor version), `observed_at`, and a `raw_payload` with
`source_url`, `evidence_text`, `referenced_domain`, and `raw_value` as
applicable. There is no evidence without provenance and no vague evidence.

## Idempotency

`observation_features` has a unique `(observation_id, feature_version)`
constraint. Re-running the same extractor version returns the existing snapshot
and creates no duplicate features or evidence. A different version creates a new
snapshot alongside the old one.

## Error handling

Malformed content never crashes the worker. Recoverable problems become
structured warnings on the snapshot (`ExtractionWarningCategory`:
`MALFORMED_URL`, `MALFORMED_HTML`, `INVALID_UNICODE`, `INVALID_EMAIL`,
`INVALID_PHONE`, `OVERSIZED_FIELD`, `UNSUPPORTED_ENCODING`,
`MALFORMED_OBSERVATION`). An unparseable payload yields an empty, warned snapshot
rather than an exception. Only a genuinely missing observation raises.

## Security boundary

Phase 4 preserves Phase 3's boundary: it does not fetch URLs, resolve DNS, make
outbound requests, bypass SSRF controls, or execute JavaScript. It reads stored
observations only.

## Service / worker / API

- Service: `run_feature_extraction(session, observation_id, extractor)` —
  broker-independent, idempotent, dependency-injectable extractor.
- Worker: Celery `dere.extract_features` task.
- API: `POST /observations/{id}/extract`, `GET /observations/{id}/features`,
  `GET /domains/{id}/features`. No matching endpoint exists.

## Future signals

`COMPANY_NAME`, `LEGAL_ENTITY`, `ADDRESS`, `OFFICIAL_WEBSITE_REFERENCE` (a
refinement of `CROSS_DOMAIN_REFERENCE`), and `TLS_CERTIFICATE` are documented in
[evidence-taxonomy.md](evidence-taxonomy.md) as future work, not fabricated.
