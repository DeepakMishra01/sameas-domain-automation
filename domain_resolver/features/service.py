"""Phase 4 feature-extraction orchestration.

Reads a persisted observation, runs the deterministic extractor, and appends a
versioned feature snapshot plus factual, provenance-bearing evidence. It never
fetches URLs, resolves DNS, or makes network calls — it consumes stored
observations only. Idempotent per (observation, feature_version).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from domain_resolver.features.errors import ExtractionWarningCategory, FeatureExtractionError
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.results import ExtractionWarning, FeatureSet
from domain_resolver.models.base import utc_now
from domain_resolver.models.entities import Evidence, ObservationFeature
from domain_resolver.observation.logging import log_event
from domain_resolver.observation.results import ObservationResult
from domain_resolver.repositories.sqlalchemy import (
    SqlAlchemyDomainObservationRepository,
    SqlAlchemyEvidenceRepository,
    SqlAlchemyObservationFeatureRepository,
)


def run_feature_extraction(
    session: Session,
    *,
    observation_id: UUID,
    extractor: FeatureExtractor,
    now: Callable[[], datetime] = utc_now,
) -> ObservationFeature:
    """Extract and persist features for one observation. Idempotent per version."""
    features_repo = SqlAlchemyObservationFeatureRepository(session)
    observations = SqlAlchemyDomainObservationRepository(session)
    evidence_repo = SqlAlchemyEvidenceRepository(session)
    version = extractor.version

    existing = features_repo.get_by_observation_and_version(observation_id, version)
    if existing is not None:
        log_event(
            "feature_extraction_idempotent_hit",
            observation_id=observation_id,
            feature_id=existing.id,
            feature_version=version,
        )
        return existing

    observation = observations.get_by_id(observation_id)
    if observation is None:
        raise FeatureExtractionError(f"observation {observation_id} does not exist")

    log_event(
        "feature_extraction_started",
        observation_id=observation_id,
        domain_id=observation.domain_id,
        feature_version=version,
    )

    result = _parse_payload(observation.payload)
    if result is None:
        # Malformed/absent payload must not crash: persist an empty, warned snapshot.
        features = FeatureSet(
            feature_version=version,
            domain_id=str(observation.domain_id),
            observation_id=str(observation.id),
        )
        warnings = [
            ExtractionWarning(
                category=ExtractionWarningCategory.MALFORMED_OBSERVATION,
                detail="observation payload could not be parsed as an ObservationResult",
                field="payload",
            )
        ]
        snapshot = features_repo.create(
            ObservationFeature(
                observation_id=observation.id,
                domain_id=observation.domain_id,
                feature_version=version,
                features=features.model_dump(mode="json"),
                warnings=[w.model_dump(mode="json") for w in warnings],
            )
        )
        log_event(
            "feature_extraction_completed",
            observation_id=observation_id,
            feature_id=snapshot.id,
            feature_version=version,
            malformed=True,
        )
        return snapshot

    output = extractor.extract(
        domain_id=observation.domain_id,
        observation_id=observation.id,
        domain_host=observation.raw_domain,
        result=result,
    )

    snapshot = features_repo.create(
        ObservationFeature(
            observation_id=observation.id,
            domain_id=observation.domain_id,
            feature_version=version,
            features=output.features.model_dump(mode="json"),
            warnings=[w.model_dump(mode="json") for w in output.warnings] or None,
        )
    )

    observed_at = now()
    for draft in output.evidence:
        evidence_repo.create(
            Evidence(
                reason_code=draft.reason_code.value,
                evidence_type=draft.category.value,
                source=version,
                domain_a_id=observation.domain_id,
                value=None,
                strength=None,
                observation_id=observation.id,
                observed_at=observed_at,
                raw_payload={
                    "source_url": draft.source_url,
                    "evidence_text": draft.evidence_text,
                    "referenced_domain": draft.referenced_domain,
                    "raw_value": draft.raw_value,
                    **draft.raw_payload,
                },
            )
        )

    log_event(
        "feature_extraction_completed",
        observation_id=observation_id,
        feature_id=snapshot.id,
        feature_version=version,
        evidence_count=len(output.evidence),
        warning_count=len(output.warnings),
    )
    return snapshot


def _parse_payload(payload: dict[str, object] | None) -> ObservationResult | None:
    if not payload:
        return None
    try:
        return ObservationResult.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return None
