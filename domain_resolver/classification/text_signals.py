"""Deterministic on-page text signals for PART_OF / ACQUIRED classification.

A signal fires only when an explicit relationship phrase (e.g. "a subsidiary of",
"acquired by") appears in a domain's own observed text *and* the peer domain is
named nearby (its name token appears in the text, or the page links to it). This
is intentionally high-precision / low-recall: it never guesses a relationship
from branding, shared contacts, or similarity alone. Pure — no network/DB.

Direction is derived from *which* page carries the phrase:
- "acquired by" / "a product of" on A's page  → A is subordinate, peer is superior.
- "has acquired" / "acquisition of"  on A's page → A is superior, peer is subordinate.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_resolver.classification.reason_codes import ClassificationReasonCode
from domain_resolver.classification.relationship_types import PartOfSubtype, RelationshipType
from domain_resolver.features import normalization as norm
from domain_resolver.matching.views import DomainFeatureView


@dataclass(frozen=True)
class TextSignal:
    """One relationship statement found on the carrier domain's page.

    ``carrier_is_subordinate`` records whether the page that carried the phrase is
    the subordinate side (child/acquired) or the superior side (parent/acquirer).
    """

    relationship_type: RelationshipType
    reason_code: ClassificationReasonCode
    subtype: PartOfSubtype | None
    matched_phrase: str
    carrier_is_subordinate: bool


@dataclass(frozen=True)
class _Rule:
    phrase: str
    relationship_type: RelationshipType
    subtype: PartOfSubtype | None
    reason_code: ClassificationReasonCode
    carrier_is_subordinate: bool


# Order matters: more specific phrases first so the specific subtype wins over the
# generic "part of" fallback. All phrases are lowercase; matched against the
# lowercased, whitespace-collapsed carrier text.
_RULES: tuple[_Rule, ...] = (
    # -- PART_OF: subordinate-carrier statements ("we are a … of <peer>") ------
    _Rule(
        "a subsidiary of",
        RelationshipType.PART_OF,
        PartOfSubtype.SUBSIDIARY,
        ClassificationReasonCode.SUBSIDIARY_OF,
        True,
    ),
    _Rule(
        "subsidiary of",
        RelationshipType.PART_OF,
        PartOfSubtype.SUBSIDIARY,
        ClassificationReasonCode.SUBSIDIARY_OF,
        True,
    ),
    _Rule(
        "a business unit of",
        RelationshipType.PART_OF,
        PartOfSubtype.BUSINESS_UNIT,
        ClassificationReasonCode.BUSINESS_UNIT_OF,
        True,
    ),
    _Rule(
        "a division of",
        RelationshipType.PART_OF,
        PartOfSubtype.DIVISION,
        ClassificationReasonCode.DIVISION_OF,
        True,
    ),
    _Rule(
        "division of",
        RelationshipType.PART_OF,
        PartOfSubtype.DIVISION,
        ClassificationReasonCode.DIVISION_OF,
        True,
    ),
    _Rule(
        "a product of",
        RelationshipType.PART_OF,
        PartOfSubtype.PRODUCT,
        ClassificationReasonCode.PRODUCT_OF,
        True,
    ),
    _Rule(
        "a product by",
        RelationshipType.PART_OF,
        PartOfSubtype.PRODUCT,
        ClassificationReasonCode.PRODUCT_OF,
        True,
    ),
    _Rule(
        "a brand of",
        RelationshipType.PART_OF,
        PartOfSubtype.BRAND,
        ClassificationReasonCode.BRAND_OF,
        True,
    ),
    _Rule(
        "a brand by",
        RelationshipType.PART_OF,
        PartOfSubtype.BRAND,
        ClassificationReasonCode.BRAND_OF,
        True,
    ),
    _Rule(
        "a brand from",
        RelationshipType.PART_OF,
        PartOfSubtype.BRAND,
        ClassificationReasonCode.BRAND_OF,
        True,
    ),
    _Rule(
        "a service of",
        RelationshipType.PART_OF,
        PartOfSubtype.SERVICE,
        ClassificationReasonCode.SERVICE_OF,
        True,
    ),
    _Rule(
        "a service by",
        RelationshipType.PART_OF,
        PartOfSubtype.SERVICE,
        ClassificationReasonCode.SERVICE_OF,
        True,
    ),
    _Rule(
        "an initiative of",
        RelationshipType.PART_OF,
        PartOfSubtype.OTHER,
        ClassificationReasonCode.PART_OF_STATEMENT,
        True,
    ),
    _Rule(
        "operated by",
        RelationshipType.PART_OF,
        PartOfSubtype.OTHER,
        ClassificationReasonCode.PART_OF_STATEMENT,
        True,
    ),
    _Rule(
        "is part of",
        RelationshipType.PART_OF,
        PartOfSubtype.OTHER,
        ClassificationReasonCode.PART_OF_STATEMENT,
        True,
    ),
    _Rule(
        "now part of",
        RelationshipType.PART_OF,
        PartOfSubtype.OTHER,
        ClassificationReasonCode.PART_OF_STATEMENT,
        True,
    ),
    _Rule(
        "part of the",
        RelationshipType.PART_OF,
        PartOfSubtype.OTHER,
        ClassificationReasonCode.PART_OF_STATEMENT,
        True,
    ),
    # -- ACQUIRED: subordinate-carrier ("we were acquired by <peer>") ---------
    _Rule(
        "has been acquired by",
        RelationshipType.ACQUIRED,
        None,
        ClassificationReasonCode.ACQUIRED_BY,
        True,
    ),
    _Rule(
        "was acquired by",
        RelationshipType.ACQUIRED,
        None,
        ClassificationReasonCode.ACQUIRED_BY,
        True,
    ),
    _Rule(
        "acquired by", RelationshipType.ACQUIRED, None, ClassificationReasonCode.ACQUIRED_BY, True
    ),
    # -- ACQUIRED: superior-carrier ("we acquired <peer>") --------------------
    _Rule(
        "has acquired",
        RelationshipType.ACQUIRED,
        None,
        ClassificationReasonCode.ACQUISITION_ANNOUNCEMENT,
        False,
    ),
    _Rule(
        "have acquired",
        RelationshipType.ACQUIRED,
        None,
        ClassificationReasonCode.ACQUISITION_ANNOUNCEMENT,
        False,
    ),
    _Rule(
        "acquisition of",
        RelationshipType.ACQUIRED,
        None,
        ClassificationReasonCode.ACQUISITION_ANNOUNCEMENT,
        False,
    ),
)


def _carrier_text(view: DomainFeatureView) -> str:
    f = view.features
    parts = [f.normalized_title, f.normalized_meta_description, f.normalized_text_excerpt]
    return norm.normalize_text(" ".join(p for p in parts if p))


def _peer_named(view: DomainFeatureView, peer: DomainFeatureView, text_tokens: set[str]) -> bool:
    """True if the peer is identifiable in the carrier's text or outbound links.

    Deterministic and conservative: we accept the peer's registrable name token
    appearing in the text, or the carrier linking to the peer. (Brand-name based
    matching is a Stage-2 enhancement.)
    """
    peer_name_tokens = norm.tokenize(norm.domain_name_key(peer.host))
    if peer_name_tokens and peer_name_tokens[-1] in text_tokens:
        return True
    return any(
        ref == peer.host or norm.is_same_site(ref, peer.host)
        for ref in view.features.referenced_domains
    )


def detect_text_signals(view: DomainFeatureView, peer: DomainFeatureView) -> list[TextSignal]:
    """Return every distinct relationship statement on ``view`` that names ``peer``."""
    text = _carrier_text(view)
    if not text:
        return []
    text_tokens = set(norm.tokenize(text))
    if not _peer_named(view, peer, text_tokens):
        return []

    signals: list[TextSignal] = []
    seen: set[ClassificationReasonCode] = set()
    for rule in _RULES:
        if rule.phrase in text and rule.reason_code not in seen:
            seen.add(rule.reason_code)
            signals.append(
                TextSignal(
                    relationship_type=rule.relationship_type,
                    reason_code=rule.reason_code,
                    subtype=rule.subtype,
                    matched_phrase=rule.phrase,
                    carrier_is_subordinate=rule.carrier_is_subordinate,
                )
            )
    return signals
