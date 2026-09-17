"""PostgreSQL-gated API tests for the observation endpoints.

The database session and observers are overridden so no real network/DNS is used;
the endpoints run against the real migrated schema. Skipped without a database.
"""

from collections.abc import Generator, Iterator
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.api.dependencies import (
    dns_observer_dependency,
    http_observer_dependency,
    session_dependency,
)
from apps.api.main import app
from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.models.entities import Company, Domain
from domain_resolver.observation.results import DnsObservation, DnsRecordSet, HttpObservation

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeDns:
    def observe(self, hostname: str) -> DnsObservation:
        return DnsObservation(
            hostname=hostname, records=[DnsRecordSet(record_type="A", values=["93.184.216.34"])]
        )


class _FakeHttp:
    def observe(self, hostname: str) -> HttpObservation:
        return HttpObservation(
            requested_url=f"https://{hostname}/",
            status_code=200,
            content_type="text/html",
            final_url=f"https://{hostname}/",
            final_hostname=hostname,
        )


async def test_observe_and_query_endpoints(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)

    with session_scope(factory) as session:
        company = Company(
            external_company_id=f"api-{uuid4().hex[:8]}",
            name_raw="Api Co",
            name_normalized="api co",
        )
        domain = Domain(hostname=f"{uuid4().hex[:8]}.api.test")
        session.add_all([company, domain])
        session.flush()
        company_id = str(company.id)
        domain_id = str(domain.id)

    def _session_override() -> Generator[Session, None, None]:
        with session_scope(factory) as session:
            yield session

    app.dependency_overrides[session_dependency] = _session_override
    app.dependency_overrides[dns_observer_dependency] = lambda: _FakeDns()
    app.dependency_overrides[http_observer_dependency] = lambda: _FakeHttp()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                f"/domains/{domain_id}/observe", json={"company_id": company_id}
            )
            assert created.status_code == 201
            body = created.json()
            observation_id = body["id"]
            assert body["payload"]["http"]["status_code"] == 200

            listed = await client.get(f"/domains/{domain_id}/observations")
            assert listed.status_code == 200
            assert any(item["id"] == observation_id for item in listed.json())

            fetched = await client.get(f"/observations/{observation_id}")
            assert fetched.status_code == 200
            assert fetched.json()["id"] == observation_id

            missing = await client.get(f"/observations/{uuid4()}")
            assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_observe_missing_domain_returns_404(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)

    def _session_override() -> Iterator[Session]:
        with session_scope(factory) as session:
            yield session

    app.dependency_overrides[session_dependency] = _session_override
    app.dependency_overrides[dns_observer_dependency] = lambda: _FakeDns()
    app.dependency_overrides[http_observer_dependency] = lambda: _FakeHttp()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/domains/{uuid4()}/observe", json={"company_id": str(uuid4())}
            )
            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
