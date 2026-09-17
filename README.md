# Domain Entity Resolution System (DERE)

DERE is an internal, evidence-first service for resolving a supplied set of candidate domains for a Tracxn company. It deliberately separates two decisions:

1. **Organization entity resolution** — whether domains belong to the same organization.
2. **Canonical domain resolution** — which confirmed organization domain is primary or secondary.

This repository currently implements the project and database foundations plus a safe domain-observation layer: configuration, Alembic migrations, PostgreSQL session infrastructure, persistence ports, a historical data model with relational evidence traceability (`decision_evidence` / `relationship_evidence` / `evidence.observation_id`), canonical relationship-pair discipline, domain normalization, a FastAPI health endpoint, and — as of Phase 3 — SSRF-resistant DNS/HTTP observation with bounded HTML extraction, factual evidence, a Celery task, and observation API endpoints. Evidence **scoring**, same-as **matching**, organization resolution, primary-domain selection, and LLM verification remain intentionally out of scope.

Phase 3 collects factual observations only ("what did we observe?") and never determines same-as relationships. See [docs/observation.md](docs/observation.md).

## Local development

```bash
cp .env.example .env
python -m venv .venv
.venv/bin/pip install -e '.[dev,postgres]'
make test
make run
```

The API health endpoint is available at `GET /health` and does not require a database connection. Database configuration is optional until database infrastructure or Alembic is invoked. Schema changes are managed only by Alembic; application startup never creates schema objects.

To migrate a configured database:

```bash
export DERE_DATABASE_URL='postgresql+psycopg://...'
.venv/bin/alembic upgrade head
```

## Current implementation plan

1. Foundation (complete): contracts, configuration, model skeleton, health API, normalization, tests.
2. Database migrations and repository adapters (complete).
3. Safe domain observation and collection (complete): SSRF-safe DNS/HTTP observation, factual evidence, worker task, API.
4. Evidence extraction and normalization.
5. Organization-resolution features and configurable rules.
6. Primary-domain resolution, evaluation, review workflows, and production hardening.

See [docs/product-requirements.md](docs/product-requirements.md), [docs/architecture.md](docs/architecture.md), and [docs/data-model.md](docs/data-model.md).
