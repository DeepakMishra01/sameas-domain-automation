# Phase 4 evidence taxonomy

Phase 4 evidence records are **facts** derived from persisted Phase 3
observations. Every code below describes *what was observed*, never *what it
means*. Nothing here asserts that two domains are the same organization — that
judgement belongs to Phase 5.

The taxonomy is versioned by the extractor (`Settings.feature_extractor_version`,
default `feature-extractor-v1`), stored on each evidence row's `source` and on
the feature snapshot's `feature_version`, so versions coexist.

## Supported codes (extractable today)

| Category | Reason code | Derived from | Provenance |
| --- | --- | --- | --- |
| IDENTITY | `EMAIL_DOMAIN` | `mailto:` links + emails in bounded text | source_url, address, domain |
| IDENTITY | `PHONE` | `tel:` links | source_url, normalized phone |
| IDENTITY | `SOCIAL_PROFILE` | links to known social platforms | source_url, normalized url, platform |
| WEBSITE | `TITLE` | HTML `<title>` | source_url, raw + normalized title |
| WEBSITE | `META_DESCRIPTION` | meta description / `og:description` | source_url, raw + normalized |
| WEBSITE | `CANONICAL_URL` | `<link rel=canonical>` | source_url, canonical url + domain |
| WEBSITE | `REDIRECT` | HTTP redirect chain | requested url, final url, target domain, chain |
| WEBSITE | `CROSS_DOMAIN_REFERENCE` | outbound links to a different site | source_url, referenced domain, link href |
| CONTENT | `CONTENT_TEXT` | bounded visible-text excerpt | source_url, normalized text, fingerprint |
| CONTENT | `CONTENT_HASH` | SHA-256 content hash from Phase 3 | source_url, hash |
| NETWORK | `DNS_A` / `DNS_AAAA` / `DNS_CNAME` / `DNS_MX` / `DNS_NS` | DNS records | record values |

Every evidence row also carries `observation_id` (FK), `domain_a_id` (the
observed domain), `source` (extractor version), and `observed_at`. Factual
evidence asserts no `strength` (left null).

`CROSS_DOMAIN_REFERENCE` is defined by comparing full normalized hostnames: a
link is a reference only when its host is neither equal to, nor a subdomain of
(nor a parent of), the observed domain's host. It is a **fact that a link
exists**, not a claim about ownership.

## Not yet supported (documented future work)

These are intentionally **not fabricated** because Phase 3 does not collect
enough deterministic data for them:

| Signal | Why deferred |
| --- | --- |
| `COMPANY_NAME` | Requires parsing/NER over titles; heuristic, not deterministic. |
| `LEGAL_ENTITY` | Requires legal-suffix parsing over content. |
| `ADDRESS` | Requires address parsing over free text. |
| `OFFICIAL_WEBSITE_REFERENCE` | A semantic refinement (rel/context) of `CROSS_DOMAIN_REFERENCE`; recorded as the latter for now. |
| `TLS_CERTIFICATE` | Phase 3 does not capture certificate details. |

## Non-goals

Phase 4 evidence never expresses similarity, ownership, primary/secondary
status, confidence thresholds, or a match. It contains no scores and calls no
LLM or embedding model.
