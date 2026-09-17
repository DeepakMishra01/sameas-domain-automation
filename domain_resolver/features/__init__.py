"""Phase 4 deterministic evidence & feature extraction.

Transforms persisted Phase 3 observations into normalized, versioned, auditable
features and factual evidence. It answers "what factual signals does this
observation contain?" — it performs no matching, similarity scoring,
primary-domain selection, or any organization judgement (those are Phase 5+).
"""

from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.results import (
    EvidenceDraft,
    ExtractionOutput,
    FeatureSet,
)
from domain_resolver.features.service import run_feature_extraction
from domain_resolver.features.taxonomy import EvidenceCategory, EvidenceReasonCode

__all__ = [
    "EvidenceCategory",
    "EvidenceDraft",
    "EvidenceReasonCode",
    "ExtractionOutput",
    "FeatureExtractor",
    "FeatureSet",
    "run_feature_extraction",
]
