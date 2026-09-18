# Phase 6 — Primary vs secondary domain resolution

Phase 6 answers one question: **within a group of domains that Phase 5 confirmed
belong to the same organization, which one is PRIMARY?** It is deterministic,
explainable, and network-free.

```
OBSERVATION (P3) → FEATURES (P4) → ORG MATCHING (P5) → PRIMARY RESOLUTION (P6) → [P7 decision]
```

## Same organization vs. primary domain

These are **different questions**, answered by different phases:

- **Phase 5:** *Are these domains the same organization?* (produces
  `DomainRelationship` groups)
- **Phase 6:** *Given they are, which one is the primary/canonical domain?*
  (produces `primary_resolutions`)

Phase 6 operates on domains already confirmed same-organization, so it never
depends on — and cannot hide — Phase 5's membership decisions. It is also
separate from the final CPT accept/reject **decision** (Phase 7).

## Purpose and non-goals

Phase 6 does **not**: decide organization membership, make the final CPT
decision, call an LLM, use embeddings/ML, crawl, resolve DNS, or make any network
call. It selects a primary from **directional evidence only**.

## Inputs and outputs

- **Input:** a company id and a set of domain ids already confirmed
  same-organization, each with Phase 4 feature snapshots.
- **Output:** a `PrimaryResolution` — `status` (`RESOLVED` / `REVIEW_REQUIRED`),
  the primary domain (or none), `confidence`, `confidence_band`, `margin`,
  per-domain `DomainScore`s (score + `PRIMARY`/`SECONDARY`/`UNRESOLVED`
  designation + reason codes), and any `conflicts`. Persisted in
  `primary_resolutions` + `primary_domain_scores`, with evidence linked through
  `primary_resolution_evidence`.

## Primary-domain signals and evidence hierarchy

All signals are **directional** facts from Phase 4 features — who points *to* whom
— never name length, age, TLD, or popularity.

| Tier | Reason code | Meaning |
| --- | --- | --- |
| VERY_STRONG | `REDIRECT_TARGET` | a peer HTTP/meta redirects **to** this domain |
| VERY_STRONG | `CANONICAL_TARGET` | a peer declares `canonical` = this domain |
| SUPPORTING | `ACTIVE_WEBSITE` | serves its own content and does not defer to a peer |
| SUPPORTING | `SELF_CANONICAL` | declares itself canonical |
| WEAK | `REFERENCED_BY_PEER` | a peer links to this domain |
| Negative | `REDIRECTS_AWAY` | this domain redirects to a peer (it defers → secondary) |
| Negative | `CANONICAL_AWAY` | this domain's canonical is a peer (defers → secondary) |

`OFFICIAL_WEBSITE_REFERENCE` and legal-entity signals are **not** produced,
because Phase 4 does not collect them; the interfaces allow adding them later.

## Fact vs. inference

The **fact** is a stored Phase 4 evidence row (e.g. a `REDIRECT`). The
**inference** ("this domain is primary") lives only in the resolver's reason
codes and score — it is never written back as evidence. `primary_domain_scores`
records the reason codes and the ids of the underlying evidence, and
`primary_resolution_evidence` links the resolution to those factual rows, so a
reviewer can trace: resolution → evidence → observation → source domain →
timestamp/version.

## Scoring

For each domain `primary_score = noisy_or(positive weights) × (1 − noisy_or(negative weights))`.
A domain that redirects/canonicals **away** to a peer has its score strongly
dampened (it is a pointer, not the destination); the domain others point to and
that serves its own content rises to the top. Weights and thresholds live in a
versioned `ResolverConfig` (persisted via `ModelVersion`, kind `RULES`); all are
**provisional** and configuration-driven, none statistically validated.

## Confidence

Configurable bands from the winner's score: `HIGH` ≥ `high_threshold`, `MEDIUM` ≥
`medium_threshold`, else `LOW` (provisional, tunable against CPT data).

## Multi-domain handling

Works for any group size. `A → B`, `C → B`, `D → B` makes B the clear target.
Contributions are weighted by the strength of the underlying evidence, not by
counting relationships. A redirect **chain** (`C → A → B`) resolves to the
terminal destination B.

## Conflict handling and unresolved cases

The resolver refuses to force an answer. A pair/group is `REVIEW_REQUIRED`
(primary `UNRESOLVED`, no domain blindly marked secondary) when:

- **mutual/cyclic** pointing (`A → B` and `B → A`) — recorded as a `conflict`;
- **ambiguous** — the top score does not beat the runner-up by `margin_threshold`;
- **insufficient** — the top score is below `decision_threshold`;
- **no directional evidence** at all.

A domain is marked `SECONDARY` only when the group resolves and another domain has
a clear, sufficiently stronger primary score.

## Versioning & idempotency

`resolver_version` (`Settings.resolver_version`, default `primary-v1`) identifies
the config; resolutions are unique per `(company, group, resolver version)`, so
re-running is idempotent and a new version coexists with older ones.

## Evaluation

`domain_resolver.resolution.evaluation` reports accuracy, coverage, confidence
distribution, and reason-code counts on labelled `(group, expected_primary)`
data, using **only** the primary decision (never the expected-primary as an input
signal). `scripts/evaluate_primary.py` runs the full pipeline over the 14 CPT
examples (treated as confirmed same-org groups) and reports metrics. The examples
are evaluation data only — **not** hard-coded; regression tests lock in
directional behaviour and assert the resolver never resolves without evidence.

## Known limitations

- Weights/thresholds are provisional (untuned against labelled data).
- No official-reference / legal-entity / company-name signals (Phase 4 gap).
- A domain that redirects to a peer carries that peer's content in its own
  feature snapshot; `ACTIVE_WEBSITE` therefore requires that the domain does not
  redirect away, so borrowed content is not mistaken for a domain's own.
- Purely ambiguous or evidence-poor groups are deliberately left for review.

## Not handled in Phase 6

The final CPT decision (auto-accept / auto-reject / send to review) is **Phase 7**.
