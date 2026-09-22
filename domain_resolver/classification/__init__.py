"""Deterministic relationship classification (SAME_AS / PART_OF / ACQUIRED / …).

Sits between Phase 5 (the matcher, which only detects *that* two domains are
related) and the final decision. It answers "*what type* of relationship is
this?" from already-collected Phase 4 features — never from an LLM, embeddings,
name length, age, TLD, or popularity. Every classification is explainable via its
reason codes and a human-readable explanation.
"""

from domain_resolver.classification.classifier import RelationshipClassifier
from domain_resolver.classification.reason_codes import ClassificationReasonCode
from domain_resolver.classification.relationship_types import (
    PartOfSubtype,
    RelationshipDirection,
    RelationshipType,
)
from domain_resolver.classification.results import RelationshipClassification

__all__ = [
    "ClassificationReasonCode",
    "PartOfSubtype",
    "RelationshipClassification",
    "RelationshipClassifier",
    "RelationshipDirection",
    "RelationshipType",
]
