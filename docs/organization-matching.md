# Phase 5 — Organization matching

Phase 5 answers exactly one question: **do two domains belong to the same
organization?** It consumes already-collected Phase 4 features and evidence and
is deterministic, explainable, and network-free.

```
OBSERVATION (P3) → EVIDENCE/FEATURES (P4) → ORGANIZATION MATCHING (P5) → [P6 primary] → [decision]
```

## Purpose and non-goals

Phase 5 does **not**: select a primary/secondary domain, produce a final CPT
decision (AUTO_ACCEPT/AUTO_REJECT), call an LLM, use embeddings or ML, apply
statistically-validated thresholds, crawl, resolve DNS, or make any network call.
It only labels pairs as same-organization (or not) with an explainable reason.

## Inputs and outputs

- **Input:** a company id and a set of candidate domain ids that already have
  Phase 4 feature snapshots.
- **Output:** per candidate pair, a `MatchResult` (`same_organization`,
  `confidence`, `confidence_band`, positive `reason_codes`,
  `negative_reason_codes`, `matcher_version`, pairwise `features`), plus
  organization `groups`. Each assessment persists as a `DomainRelationship`
  (canonical `domain_a_id < domain_b_id`) with `RelationshipEvidence` links to
  the supporting Phase 4 evidence.

## Candidate generation

To avoid comparing every domain with every other, candidates are proposed from
shared-signal co-occurrence (email domain, phone, social profile, referenced
domains, DNS values), structural edges (redirect / canonical / reference targets
that resolve to another observed domain), and domain-name similarity. Candidate
generation **never** decides same-organization — it only narrows the pairs the
matcher evaluates. The matcher can also be called directly on any explicit pair
(as the evaluation harness does).

## Pairwise features

For a pair, deterministic signals are computed from both domains' features:
redirect/canonical/reference relationship (and mutual reference), same email
domain / phone / social profile, content-fingerprint match, title/meta/content
token-Jaccard similarity, shared referenced domains, DNS overlap, domain-name
similarity, and the contradictions "different email domain" / "different phone".
Every signal carries the values that caused it (stored in `match_features`).

## Evidence hierarchy

Reason codes map to evidence-strength tiers (reusing `EvidenceStrength`):

| Tier | Reason codes |
| --- | --- |
| VERY_STRONG | `REDIRECT`, `CANONICAL_URL`, `CROSS_DOMAIN_REFERENCE_MUTUAL` |
| STRONG | `CROSS_DOMAIN_REFERENCE`, `SAME_EMAIL_DOMAIN`, `SAME_PHONE`, `SAME_SOCIAL_PROFILE`, `CONTENT_FINGERPRINT_MATCH` |
| SUPPORTING | `SIMILAR_TITLE`, `SIMILAR_META`, `SIMILAR_CONTENT`, `SHARED_REFERENCED_DOMAINS`, `DNS_OVERLAP` |
| WEAK | `DOMAIN_NAME_SIMILARITY` |
| Negative | `DIFFERENT_EMAIL_DOMAIN`, `DIFFERENT_PHONE` |

These weights are **provisional** and configuration-driven; none is claimed to be
statistically validated. "Same legal entity" / "same address" are listed in the
hierarchy conceptually but are **not** produced yet, because Phase 4 does not
collect that data — the interfaces allow adding them later without a rewrite.

## Matching rules and confidence

Confidence is a deterministic noisy-OR of the fired positive signals' weights
(`1 - Π(1 - wᵢ)`), multiplicatively dampened by contradictions
(`× (1 - noisy_or(negatives))`). A pair is `same_organization` when confidence
≥ `decision_threshold`. Bands: `HIGH` ≥ `high_threshold`, `MEDIUM` ≥
`medium_threshold`, else `LOW`. Weak evidence alone never crosses the threshold;
a single contradiction never auto-rejects — it only lowers confidence. Every
positive decision lists the reason codes and links the evidence that caused it,
so no match is unexplained.

## Configuration and versioning

All weights and thresholds live in `MatcherConfig` (Pydantic), identified by
`matcher_version` (`Settings.matcher_version`, default `org-matcher-v1`). The
config is persisted in `ModelVersion.configuration` (kind `RULES`), and every
`DomainRelationship` references its `model_version_id`, so assessments are
reproducible and versions coexist for later evaluation against CPT data.

## Organization grouping

Groups are the connected components of confident positive matches (union-find).
This makes membership transitive over confident **direct** matches (A–B and B–C
place A, B, C in one group). This is a documented modeling choice: each group
records the direct edges that formed it, so a reviewer can see that A–C may be
*inferred through* B rather than directly matched. No inferred A–C pair is
fabricated or persisted as a direct match.

## Provenance / traceability

`match → DomainRelationship.reason_codes/match_features → RelationshipEvidence →
Evidence → observation_id → source domain → observed_at/collector_version`. The
matcher never copies large evidence payloads into the relationship; it links
evidence ids.

## Evaluation methodology

`domain_resolver.matching.evaluation` computes precision/recall/F1 and a
reason-code breakdown from labelled pairs, using only the same-organization
decision (never the expected primary domain). `scripts/evaluate_model.py` runs
the full pipeline (observe → extract → match) over the 14 CPT Same-As examples
and reports metrics. The 14 examples are evaluation/regression data only and are
**not** hard-coded into the matcher; regression tests lock in each supported
evidence type and assert the matcher never matches without evidence.

## Known limitations

- Weights/thresholds are provisional (not tuned against labelled data yet).
- No legal-entity/address/company-name signals (Phase 4 does not collect them).
- Domain-name similarity uses the name label with the final TLD label removed,
  not a public-suffix-aware registrable domain.
- Contradiction handling dampens rather than hard-rejects (documented).

## Not handled in Phase 5

Primary/secondary domain selection, final decisions, LLM/embeddings/ML, and any
network access. Those belong to Phase 6 and later.
