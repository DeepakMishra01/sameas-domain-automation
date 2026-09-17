# Data model

All tables use UUID primary keys and UTC timestamps. The initial schema is managed by Alembic revision `20260917_0001`; application startup never creates or mutates schema.

| Table | Purpose | History policy |
| --- | --- | --- |
| `companies` | CPT company identity and raw/normalized name | mutable current identity; `created_at` + `updated_at` |
| `domains` | normalized registrable host and raw input | stable domain record |
| `domain_observations` | crawl/availability/source snapshot | append only |
| `domain_relationships` | pairwise organization relationship assessment | append assessment versions |
| `evidence` | attributable evidence with raw payload | append only |
| `decision_evidence` | link rows tracing a decision to supporting evidence | append only |
| `relationship_evidence` | link rows tracing a relationship assessment to supporting evidence | append only |
| `decisions` | company-level resolver outcome | append decision versions |
| `human_reviews` | CPT reviewer correction/feedback | append only |
| `human_review_secondary_domains` | normalized corrected-secondary links for a review | append only |
| `model_versions` | rule/model/feature configuration identity | immutable version records |
| `crawl_jobs` | asynchronous crawl lifecycle | mutable status; `created_at` + `updated_at`, retain output/error |

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

## Relationship pair discipline

A `domain_relationships` row is symmetric: `domain_a_id` and `domain_b_id` identify an unordered pair. Rows are stored in a single canonical direction enforced by the check constraint `canonical_domain_order` (`domain_a_id < domain_b_id`), which PostgreSQL evaluates using the total ordering it defines for the `uuid` type. The `SqlAlchemyDomainRelationshipRepository` canonicalizes the pair before persisting.

This guarantees the same unordered pair is never stored as two opposite-direction rows, while still allowing multiple **historical** assessments of that pair (for example under different `model_version_id` values or repeated re-assessments). No uniqueness constraint is placed across the pair, precisely so legitimate historical versions are retained.
