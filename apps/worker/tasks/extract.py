"""Celery task wrapping deterministic Phase 4 feature extraction.

Idempotent per (observation, feature_version), retryable, and observation-only
(no network/DNS). A failure for one observation raises only for that task.
"""

from __future__ import annotations

from uuid import UUID

from apps.worker.celery_app import celery_app
from domain_resolver.config.settings import get_settings
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="dere.extract_features",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def extract_features(self: object, observation_id: str) -> str:
    """Extract and persist features for one observation; returns the snapshot id."""
    settings = get_settings()
    session_factory = create_session_factory(create_engine_from_settings(settings))
    extractor = FeatureExtractor(settings.feature_extractor_version)
    with session_scope(session_factory) as session:
        snapshot = run_feature_extraction(
            session, observation_id=UUID(observation_id), extractor=extractor
        )
        return str(snapshot.id)
