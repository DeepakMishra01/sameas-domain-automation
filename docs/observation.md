# Phase 3 — Safe domain observation

The observer answers exactly one question: **what did we observe about a
candidate domain?** It performs no same-as matching, organization resolution,
scoring, primary/secondary selection, LLM, or embedding work — those belong to
later phases. Nothing in this layer concludes that two domains are the same
organization.

```
Observer  = WHAT DID WE OBSERVE?      ← Phase 3 (this document)
Matcher   = WHAT DOES THE EVIDENCE MEAN?
Decision  = WHAT SHOULD WE DO?
```

## Input

The observer receives a `company_id` and a `domain_id` for a candidate domain
already discovered by CPT. It never performs broad web-wide domain discovery.

## Observation lifecycle

```
observe(company_id, domain_id, idempotency_key)
        │
        ▼
crawl_jobs: PENDING → RUNNING ───────────────► SUCCEEDED / FAILED
        │                                        ▲
        ├─ DNS observation  (A/AAAA/CNAME/MX/NS) │
        ├─ HTTP observation (HTTPS→HTTP, redirects, HTML)
        ▼                                        │
domain_observations (append-only snapshot) ──────┘
        │
        ▼
evidence (factual: REDIRECT, CANONICAL_URL) ── observation_id ──► traceable
```

Every distinct run appends a new `domain_observations` row (history is never
overwritten). Re-running with an `idempotency_key` whose job already succeeded
returns the existing observation instead of creating a duplicate.

## Security / SSRF model

Defensive by default. Before any connection:

* only `http`/`https` and ports 80/443 are permitted;
* the hostname is resolved and **every** resulting IP is validated — one
  disallowed address blocks the request;
* loopback, private, link-local (including the `169.254.169.254` cloud metadata
  address), multicast, reserved, and unspecified ranges are rejected for IPv4
  and IPv6, and IPv4-mapped IPv6 is unwrapped and re-checked;
* `localhost` and known metadata hostnames are rejected by name;
* connections are **pinned** to the validated IP (the socket connects to that
  exact address while SNI/Host/cert-verification use the original hostname),
  closing the DNS-rebinding window between validation and connect;
* every redirect target is re-validated before it is followed, so a redirect can
  never reach a blocked/private address;
* response body size, redirect count, per-phase timeouts, and a total wall-clock
  timeout are all bounded.

Bodies, headers with credentials, and secrets are never logged.

## DNS observation

Collects `A`, `AAAA`, `CNAME`, `MX`, `NS` where available, recording values,
per-record errors, and observation timestamp. `NXDOMAIN`, timeouts, and
resolver errors are captured as structured facts and never crash the job. DNS
similarity is never treated as proof of ownership.

## HTTP observation

Attempts HTTPS first, falling back to HTTP only on a transport-level failure
(TLS/connection/timeout). Captures requested URL, status, a bounded set of
headers, content type, response size, timing, the redirect chain, final URL, and
final hostname. HTTP status codes and failures are recorded as observations —
a 403/404/timeout/DNS failure is **never** interpreted as dead, unrelated, or
same.

## Redirect handling

Redirects are followed manually (`follow_redirects=False`). The complete chain
is persisted as fact (source URL, status code, location, target). Loops are
detected, the redirect count is bounded, and every target is validated. A chain
such as `zeptonow.com → www.zeptonow.com → zepto.com` is recorded as observed
hops and never as a `zeptonow.com = zepto.com` conclusion.

## Error taxonomy

`ObservationErrorCategory`: `DNS_ERROR`, `TIMEOUT`, `ROBOTS_BLOCKED`, `HTTP_403`,
`HTTP_429`, `HTTP_4XX`, `HTTP_5XX`, `SSL_ERROR`, `CONNECTION_ERROR`,
`PARSER_ERROR`, `RESPONSE_TOO_LARGE`, `REDIRECT_LIMIT`, `SSRF_BLOCKED`. A
category is recorded only when the failure can be classified with confidence;
ambiguous failures are left uncategorised with detail preserved.

## HTML extraction

When a successful HTML response is available, a bounded, deterministic
standard-library parser extracts only: `<title>`, meta description (with
`og:description` fallback), canonical URL, links (deduped and capped), a bounded
text excerpt, and a SHA-256 content hash. JavaScript is never executed and
Playwright is not used. No company identity, legal entity, or relationship is
extracted here.

## Observation persistence

The existing `domain_observations` table is extended (not replaced) with
`collector_version`, `error_category`, and `error_detail`; the full structured
result is stored in `payload`. Rows are append-only. `crawl_jobs` carries the
job lifecycle (status, started/completed timestamps, idempotency key, result
summary).

## Evidence contract

Phase 3 may create only **factual** evidence, each linked to its source
observation via `evidence.observation_id`:

* `REDIRECT` — "domain returned an HTTP redirect to <url>";
* `CANONICAL_URL` — "page declared canonical URL <url>".

It never creates `SAME_ORGANIZATION`, `PRIMARY_DOMAIN`, or any interpretive
evidence. Factual evidence asserts no `strength` (weight is left null).

## API

* `POST /domains/{domain_id}/observe` — trigger an observation (body:
  `company_id`, optional `idempotency_key`).
* `GET /domains/{domain_id}/observations` — list a domain's observations.
* `GET /observations/{observation_id}` — fetch one observation.

No matching, resolution, or decision endpoint exists in Phase 3.

## Worker / task

`apps.worker.tasks.observe.observe_domain` is a Celery task wrapping the
broker-independent `run_domain_observation` service. It is idempotent (keyed by
`idempotency_key`), retryable, bounded, and observable; a failure for one domain
raises only for that task and never affects other domains.

## Collector version

`Settings.collector_version` (default `domain-observer-v1`, env
`DERE_COLLECTOR_VERSION`) is defined once and stored on every observation so
historical rows remain attributable to the collector that produced them.

## Testing strategy

* Unit tests (no network, no DB): SSRF/URL validation, private/loopback/reserved
  IP rejection, redirect validation/loop/limit, timeout and error classification,
  response-size limit, DNS error handling, HTML extraction, content hashing —
  driven by an in-memory `httpx.MockTransport` and a mocked resolver.
* Security tests: explicit blocks for `127.0.0.1`, `localhost`, private IPv4/IPv6,
  link-local, cloud metadata, and both direct and redirect-based SSRF.
* Integration tests (PostgreSQL-gated, skipped without `DERE_TEST_DATABASE_URL`,
  never substituted with SQLite): observation persistence, historical
  observations, idempotency, evidence linkage, job lifecycle, and the API.

The normal test suite never depends on real external websites.
