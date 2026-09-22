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

    # Confidence banding (provisional; not statistically validated).
    high_threshold: float = 0.80
    medium_threshold: float = 0.50

    def to_configuration(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


DEFAULT_CLASSIFIER_CONFIG = ClassifierConfig()
