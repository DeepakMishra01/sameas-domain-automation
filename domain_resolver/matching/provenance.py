"""Maps a pairwise match reason code to the Phase 4 evidence codes that back it.

Used to link a persisted relationship to the concrete Phase 4 evidence rows that
support each fired signal, so a reviewer can trace: match -> evidence ->
observation -> source domain -> timestamp/version.
"""

from __future__ import annotations

from domain_resolver.features.taxonomy import EvidenceReasonCode as P4
from domain_resolver.matching.reason_codes import MatchReasonCode

MATCH_CODE_TO_EVIDENCE_CODES: dict[MatchReasonCode, frozenset[str]] = {
    MatchReasonCode.REDIRECT: frozenset({P4.REDIRECT}),
    MatchReasonCode.CANONICAL_URL: frozenset({P4.CANONICAL_URL}),
    MatchReasonCode.CROSS_DOMAIN_REFERENCE: frozenset({P4.CROSS_DOMAIN_REFERENCE}),
    MatchReasonCode.CROSS_DOMAIN_REFERENCE_MUTUAL: frozenset({P4.CROSS_DOMAIN_REFERENCE}),
    MatchReasonCode.SAME_EMAIL_DOMAIN: frozenset({P4.EMAIL_DOMAIN}),
    MatchReasonCode.SAME_PHONE: frozenset({P4.PHONE}),
    MatchReasonCode.SAME_SOCIAL_PROFILE: frozenset({P4.SOCIAL_PROFILE}),
    MatchReasonCode.CONTENT_FINGERPRINT_MATCH: frozenset({P4.CONTENT_HASH, P4.CONTENT_TEXT}),
    MatchReasonCode.SIMILAR_TITLE: frozenset({P4.TITLE}),
    MatchReasonCode.SIMILAR_META: frozenset({P4.META_DESCRIPTION}),
    MatchReasonCode.SIMILAR_CONTENT: frozenset({P4.CONTENT_TEXT}),
    MatchReasonCode.SHARED_REFERENCED_DOMAINS: frozenset({P4.CROSS_DOMAIN_REFERENCE}),
    MatchReasonCode.DNS_OVERLAP: frozenset(
        {P4.DNS_A, P4.DNS_AAAA, P4.DNS_CNAME, P4.DNS_MX, P4.DNS_NS}
    ),
    # Derived purely from domain names; no underlying evidence row.
    MatchReasonCode.DOMAIN_NAME_SIMILARITY: frozenset(),
}
