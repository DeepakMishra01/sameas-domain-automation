"""Pairwise match reason codes and their polarity.

A reason code names a deterministic, explainable signal computed from two
domains' Phase 4 features. Positive codes support "same organization"; negative
codes are contradictory signals. Codes are mapped to evidence-strength tiers in
:mod:`domain_resolver.matching.config`, never hard-coded to any company.
"""

from __future__ import annotations

from enum import StrEnum


class MatchReasonCode(StrEnum):
    # Very strong / strong structural links between the two domains
    REDIRECT = "REDIRECT"
    CANONICAL_URL = "CANONICAL_URL"
    CROSS_DOMAIN_REFERENCE_MUTUAL = "CROSS_DOMAIN_REFERENCE_MUTUAL"
    CROSS_DOMAIN_REFERENCE = "CROSS_DOMAIN_REFERENCE"
    # Shared identity signals
    SAME_EMAIL_DOMAIN = "SAME_EMAIL_DOMAIN"
    SAME_PHONE = "SAME_PHONE"
    SAME_SOCIAL_PROFILE = "SAME_SOCIAL_PROFILE"
    # Supporting content/network similarity
    CONTENT_FINGERPRINT_MATCH = "CONTENT_FINGERPRINT_MATCH"
    SIMILAR_TITLE = "SIMILAR_TITLE"
    SIMILAR_META = "SIMILAR_META"
    SIMILAR_CONTENT = "SIMILAR_CONTENT"
    SHARED_REFERENCED_DOMAINS = "SHARED_REFERENCED_DOMAINS"
    DNS_OVERLAP = "DNS_OVERLAP"
    # Weak
    DOMAIN_NAME_SIMILARITY = "DOMAIN_NAME_SIMILARITY"
    # Negative / contradictory
    DIFFERENT_EMAIL_DOMAIN = "DIFFERENT_EMAIL_DOMAIN"
    DIFFERENT_PHONE = "DIFFERENT_PHONE"


NEGATIVE_CODES: frozenset[MatchReasonCode] = frozenset(
    {MatchReasonCode.DIFFERENT_EMAIL_DOMAIN, MatchReasonCode.DIFFERENT_PHONE}
)

POSITIVE_CODES: frozenset[MatchReasonCode] = frozenset(
    code for code in MatchReasonCode if code not in NEGATIVE_CODES
)
