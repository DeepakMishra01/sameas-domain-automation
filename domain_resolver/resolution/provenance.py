"""Maps a primary reason code to the Phase 4 evidence codes that back it.

Distinguishes fact from inference: the *fact* is a stored Phase 4 evidence row
(e.g. a REDIRECT). The *inference* ("this domain is primary") lives in the
resolver's reason codes and score — never persisted as evidence itself.
"""

from __future__ import annotations

from domain_resolver.features.taxonomy import EvidenceReasonCode as P4
from domain_resolver.resolution.reason_codes import PrimaryReasonCode

PRIMARY_CODE_TO_EVIDENCE: dict[PrimaryReasonCode, frozenset[str]] = {
    PrimaryReasonCode.REDIRECT_TARGET: frozenset({P4.REDIRECT}),
    PrimaryReasonCode.CANONICAL_TARGET: frozenset({P4.CANONICAL_URL}),
    PrimaryReasonCode.SELF_CANONICAL: frozenset({P4.CANONICAL_URL}),
    PrimaryReasonCode.REFERENCED_BY_PEER: frozenset({P4.CROSS_DOMAIN_REFERENCE}),
    PrimaryReasonCode.ACTIVE_WEBSITE: frozenset({P4.TITLE, P4.CONTENT_TEXT, P4.CONTENT_HASH}),
}
