"""Versioned, configuration-driven relationship-classifier settings.

All values are **provisional** and configuration-driven so they can be tuned
against CPT-labelled data later; none is claimed to be statistically validated.
The config serialises for persistence via ``ModelVersion.configuration`` so any
stored classification is reproducible.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

CLASSIFIER_VERSION = "relationship-classifier-v1"


class ClassifierConfig(BaseModel):
    """Deterministic relationship-classifier configuration."""

    version: str = CLASSIFIER_VERSION

    # Confidence assigned to each outcome (provisional). SAME_AS requires an
    # observed redirect; a canonical tag alone never yields SAME_AS (it routes to
    # REVIEW), so there is no canonical-SAME_AS confidence.
    confidence_redirect_same_as: float = 0.95
    confidence_acquired: float = 0.85
    confidence_part_of_subtype: float = 0.80
    confidence_part_of_generic: float = 0.70
    # Name-morphology PART_OF (same registrable name / branch prefix). The
    # relationship is high-precision; the parent direction is a heuristic, hence
    # a medium confidence.
    confidence_part_of_name: float = 0.65
    # Both domains redirect to the same domain -> same entity (SAME_AS).
    confidence_common_redirect: float = 0.92
    # Shared brand/organization identity -> PART_OF (name can be coincidental).
    confidence_part_of_identity: float = 0.55
    # No strong signal but a CPT candidate -> assumed part-of (flagged, low conf).
    confidence_part_of_assumed: float = 0.3

    # Confidence banding (provisional; not statistically validated).
    high_threshold: float = 0.80
    medium_threshold: float = 0.50

    def to_configuration(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


DEFAULT_CLASSIFIER_CONFIG = ClassifierConfig()
