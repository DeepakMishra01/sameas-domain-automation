"""PostgreSQL-gated API tests for the Phase 4 feature endpoints."""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.api.dependencies import feature_extractor_dependency, session_dependency
from apps.api.main import app
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.models.entities import Company, Domain, DomainObservation, DomainState
from domain_resolver.observation.results import (
    DnsObservation,
    HttpObservation,
    ObservationResult,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _payload(host: str) -> dict[str, object]:
    http = HttpObservation(
        requested_url=f"https://{host}/",
        status_code=200,
        content_type="text/html",
        final_url=f"https://{host}/",
        final_hostname=host,
    )
    return ObservationResult(
        collector_version="c",
        observed_at=datetime.now(UTC),
        dns=DnsObservation(hostname=host),
        http=http,
    ).model_dump(mode="json")


async def test_extract_and_query_feature_endpoints(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        host = f"{uuid4().hex[:8]}.api.test"
        company = Company(
            external_company_id=f"fa-{uuid4().hex[:8]}",
            name_raw="Fa Co",
            name_normalized="fa co",
        )
        domain = Domain(hostname=host)
        session.add_all([company, domain])
        session.flush()
        observation = DomainObservation(
            company_id=company.id,
            domain_id=domain.id,
            raw_domain=host,
            state=DomainState.UNKNOWN,
            collector_version="c",
            payload=_payload(host),
        )
        session.add(observation)
        session.flush()
        observation_id = str(observation.id)
        domain_id = str(domain.id)

    def _session_override() -> Generator[Session, None, None]:
        with session_scope(factory) as session:
            yield session

    app.dependency_overrides[session_dependency] = _session_override
    app.dependency_overrides[feature_extractor_dependency] = lambda: FeatureExtractor(
        "feature-extractor-v1"
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(f"/observations/{observation_id}/extract")
            assert created.status_code == 201
            body = created.json()
            assert body["feature_version"] == "feature-extractor-v1"
            feature_id = body["id"]

            by_obs = await client.get(f"/observations/{observation_id}/features")
            assert by_obs.status_code == 200
            assert any(item["id"] == feature_id for item in by_obs.json())

            by_domain = await client.get(f"/domains/{domain_id}/features")
            assert by_domain.status_code == 200
            assert any(item["id"] == feature_id for item in by_domain.json())

            missing = await client.post(f"/observations/{uuid4()}/extract")
            assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
