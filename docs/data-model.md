# Data model

All tables use UUID primary keys and UTC timestamps. The initial schema is managed by Alembic revision `20260917_0001`; application startup never creates or mutates schema.

| Table | Purpose | History policy |
| --- | --- | --- |
| `companies` | CPT company identity and raw/normalized name | mutable current identity; `created_at` + `updated_at` |
| `domains` | normalized registrable host and raw input | stable domain record |
| `domain_observations` | crawl/availability/source snapshot (+ `collector_version`, `error_category`, `error_detail`, structured `payload`) | append only |
| `domain_relationships` | pairwise same-organization assessment (Phase 5: `same_organization`, `confidence`, `reason_codes`, `match_features`, `model_version_id`) | append assessment versions; canonical `domain_a_id < domain_b_id` |
| `evidence` | attributable evidence with raw payload | append only |
| `decision_evidence` | link rows tracing a decision to supporting evidence | append only |
| `relationship_evidence` | link rows tracing a relationship assessment to supporting evidence | append only |
| `primary_resolutions` | Phase 6 primary/secondary resolution for a same-org group (separate from `decisions`) | append; unique `(company, group, resolver version)` |
| `primary_domain_scores` | per-domain primary score + designation within a resolution | append |
| `primary_resolution_evidence` | resolution → supporting evidence links | append; unique pair |
| `decisions` | final CPT accept/reject decision (Phase 7) | append decision versions |
| `human_reviews` | CPT reviewer correction/feedback | append only |
| `human_review_secondary_domains` | normalized corrected-secondary links for a review | append only |
| `model_versions` | rule/model/feature configuration identity | immutable version records |
| `crawl_jobs` | asynchronous crawl lifecycle | mutable status; `created_at` + `updated_at`, retain output/error |
| `observation_features` | Phase 4 normalized, versioned feature snapshot per observation | append only; unique `(observation_id, feature_version)` |

`domain_observations` and `evidence` retain `observed_at`, raw values/payloads, and source context. `decisions` and `domain_relationships` reference `model_versions` by foreign key. Historical facts have no repository update operation; only crawl-job lifecycle state can be persisted through `save`. Foreign keys are `RESTRICT` to prevent accidental loss of retained facts.

## Evidence codes are a reusable taxonomy

`evidence.reason_code` (for example `SAME_COMPANY_NAME`, `SAME_PHONE`, `OFFICIAL_WEBSITE_REFERENCE`, `REDIRECT`, `CANONICAL_URL`) is a reusable taxonomy value, **not** a globally unique row identifier. The same code recurs across companies, domains, observations, and crawl times, so the column is indexed but intentionally not unique. Each evidence row is identified by its own UUID primary key.

## Evidence traceability

Material outcomes are linked to their evidence relationally rather than only through opaque JSON:

```
Decision                DomainRelationship
   │                          │
   ▼                          ▼
DecisionEvidence        RelationshipEvidence
   │                          │
   └──────────► Evidence ◄─────┘
                    │
                    ▼
        Observation / domain source
                (raw_payload)
```

`decision_evidence(decision_id, evidence_id)` and `relationship_evidence(relationship_id, evidence_id)` each carry foreign keys with `RESTRICT` delete semantics and a uniqueness constraint on the pair, so evidence cannot be double-linked and links cannot reference nonexistent evidence. Structured detail may still live in `evidence.raw_payload`, `decision.outcome_payload`, and relationship rows, but relational traceability is authoritative.

Factual observation evidence (Phase 3) is additionally traceable to its source via the nullable `evidence.observation_id` foreign key to `domain_observations` (`RESTRICT`). Such evidence is purely factual (`REDIRECT`, `CANONICAL_URL`) and asserts no `strength` (the column is nullable and left null); interpretive weights are a later-phase concern. See [observation.md](observation.md).

## Relationship pair discipline

A `domain_relationships` row is symmetric: `domain_a_id` and `domain_b_id` identify an unordered pair. Rows are stored in a single canonical direction enforced by the check constraint `canonical_domain_order` (`domain_a_id < domain_b_id`), which PostgreSQL evaluates using the total ordering it defines for the `uuid` type. The `SqlAlchemyDomainRelationshipRepository` canonicalizes the pair before persisting.

This guarantees the same unordered pair is never stored as two opposite-direction rows, while still allowing multiple **historical** assessments of that pair (for example under different `model_version_id` values or repeated re-assessments). No uniqueness constraint is placed across the pair, precisely so legitimate historical versions are retained.
