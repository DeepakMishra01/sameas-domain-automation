"""A typed view over a persisted Phase 4 feature snapshot for one domain."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from domain_resolver.features.results import FeatureSet
from domain_resolver.models.entities import ObservationFeature


@dataclass(frozen=True)
class DomainFeatureView:
    """Everything the matcher needs about one domain, with provenance ids."""

    domain_id: UUID
    observation_id: UUID
    host: str
    features: FeatureSet

    @classmethod
    def from_snapshot(cls, snapshot: ObservationFeature, host: str) -> DomainFeatureView:
        return cls(
            domain_id=snapshot.domain_id,
            observation_id=snapshot.observation_id,
            host=host,
            features=FeatureSet.model_validate(snapshot.features),
        )
