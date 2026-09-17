"""PostgreSQL integration tests for Phase 4 feature extraction.

Requires a real database (``DERE_TEST_DATABASE_URL``); skipped, never faked with
SQLite, when none is configured. Covers persistence, provenance, idempotency,
coexisting extractor versions, history preservation, and malformed payloads.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from domain_resolver.features.errors import FeatureExtractionError
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.infrastructure.database import create_session_factory, session_scope
from domain_resolver.models.entities import (
    Company,
    Domain,
    DomainObservation,
    DomainState,
    Evidence,
    ObservationFeature,
)
from domain_resolver.observation.results import (
    DnsObservation,
    DnsRecordSet,
    HtmlSummary,
    HttpObservation,
    ObservationResult,
)

pytestmark = pytest.mark.integration


def _payload(host: str) -> dict[str, object]:
    html = HtmlSummary(
        title=f"{host} Home",
        meta_description="desc",
        canonical_url=f"https://{host}/",
        links=["https://partner.io/x", "mailto:hi@" + host, "https://www.linkedin.com/company/x/"],
        text_excerpt="welcome",
        content_hash="hash1",
    )
    http = HttpObservation(
        requested_url=f"https://{host}/",
        status_code=200,
        content_type="text/html",
        final_url=f"https://{host}/",
        final_hostname=host,
        html=html,
    )
    dns = DnsObservation(hostname=host, records=[DnsRecordSet(record_type="A", values=["1.2.3.4"])])
    return ObservationResult(
        collector_version="domain-observer-test",
        observed_at=datetime.now(UTC),
        dns=dns,
        http=http,
    ).model_dump(mode="json")


def _seed_observation(session: object, *, payload: dict[str, object] | None = None) -> object:
    host = f"{uuid4().hex[:8]}.example.test"
    company = Company(
        external_company_id=f"feat-{uuid4().hex[:8]}",
        name_raw="Feat Co",
        name_normalized="feat co",
    )
    domain = Domain(hostname=host)
    session.add_all([company, domain])  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    observation = DomainObservation(
        company_id=company.id,
        domain_id=domain.id,
        source="domain-observer-test",
        raw_domain=host,
        state=DomainState.UNKNOWN,
        collector_version="domain-observer-test",
        payload=payload if payload is not None else _payload(host),
    )
    session.add(observation)  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    return observation


def test_features_and_evidence_are_persisted_with_provenance(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        observation = _seed_observation(session)
        snapshot = run_feature_extraction(
            session,
            observation_id=observation.id,
            extractor=FeatureExtractor("feature-extractor-v1"),
        )
        assert snapshot.feature_version == "feature-extractor-v1"
        assert snapshot.observation_id == observation.id
        assert snapshot.features["referenced_domains"] == ["partner.io"]

        evidence = list(
            session.scalars(select(Evidence).where(Evidence.observation_id == observation.id))
        )
        assert evidence
        for row in evidence:
            assert row.observation_id == observation.id  # provenance: observation
            assert row.source == "feature-extractor-v1"  # provenance: extractor version
            assert row.domain_a_id == observation.domain_id  # provenance: domain
            assert row.strength is None


def test_extraction_is_idempotent_per_version(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    extractor = FeatureExtractor("feature-extractor-v1")
    with session_scope(factory) as session:
        observation = _seed_observation(session)
        first = run_feature_extraction(session, observation_id=observation.id, extractor=extractor)
        evidence_after_first = session.scalar(
            select(func.count())
            .select_from(Evidence)
            .where(Evidence.observation_id == observation.id)
        )
        second = run_feature_extraction(session, observation_id=observation.id, extractor=extractor)
        assert second.id == first.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(ObservationFeature)
                .where(ObservationFeature.observation_id == observation.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.observation_id == observation.id)
            )
            == evidence_after_first
        )


def test_multiple_extractor_versions_coexist(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        observation = _seed_observation(session)
        run_feature_extraction(
            session,
            observation_id=observation.id,
            extractor=FeatureExtractor("feature-extractor-v1"),
        )
        run_feature_extraction(
            session,
            observation_id=observation.id,
            extractor=FeatureExtractor("feature-extractor-v2"),
        )
        versions = set(
            session.scalars(
                select(ObservationFeature.feature_version).where(
                    ObservationFeature.observation_id == observation.id
                )
            )
        )
        assert versions == {"feature-extractor-v1", "feature-extractor-v2"}
        # Historical evidence from both versions coexists (nothing overwritten).
        sources = set(
            session.scalars(
                select(Evidence.source).where(Evidence.observation_id == observation.id)
            )
        )
        assert {"feature-extractor-v1", "feature-extractor-v2"}.issubset(sources)


def test_malformed_payload_is_handled(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        observation = _seed_observation(session, payload={"unexpected": "shape"})
        snapshot = run_feature_extraction(
            session,
            observation_id=observation.id,
            extractor=FeatureExtractor("feature-extractor-v1"),
        )
        assert snapshot.warnings is not None
        assert snapshot.warnings[0]["category"] == "MALFORMED_OBSERVATION"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.observation_id == observation.id)
            )
            == 0
        )


def test_missing_observation_raises(migrated_engine: Engine) -> None:
    factory = create_session_factory(migrated_engine)
    with session_scope(factory) as session:
        with pytest.raises(FeatureExtractionError):
            run_feature_extraction(
                session,
                observation_id=uuid4(),
                extractor=FeatureExtractor("feature-extractor-v1"),
            )
