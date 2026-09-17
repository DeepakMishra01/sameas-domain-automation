"""Versioned Phase 4 evidence taxonomy.

Every code here is a *factual* signal derivable from persisted Phase 3
observations. Codes describe what was observed, never what it means: nothing
here asserts that two domains belong to the same organization — that is a Phase 5
concern.

Only codes actually supported by current observations are enumerated in
:class:`EvidenceReasonCode`. Signals that Phase 3 does not yet collect enough
data for are listed in :data:`FUTURE_SIGNALS` as documented future work rather
than fabricated.
"""

from __future__ import annotations

from enum import StrEnum


class EvidenceCategory(StrEnum):
    IDENTITY = "IDENTITY"
    WEBSITE = "WEBSITE"
    CONTENT = "CONTENT"
    NETWORK = "NETWORK"


class EvidenceReasonCode(StrEnum):
    """Supported, factual evidence reason codes (extractable today)."""

    # IDENTITY
    EMAIL_DOMAIN = "EMAIL_DOMAIN"
    PHONE = "PHONE"
    SOCIAL_PROFILE = "SOCIAL_PROFILE"
    # WEBSITE
    TITLE = "TITLE"
    META_DESCRIPTION = "META_DESCRIPTION"
    CANONICAL_URL = "CANONICAL_URL"
    REDIRECT = "REDIRECT"
    CROSS_DOMAIN_REFERENCE = "CROSS_DOMAIN_REFERENCE"
    # CONTENT
    CONTENT_TEXT = "CONTENT_TEXT"
    CONTENT_HASH = "CONTENT_HASH"
    # NETWORK
    DNS_A = "DNS_A"
    DNS_AAAA = "DNS_AAAA"
    DNS_CNAME = "DNS_CNAME"
    DNS_MX = "DNS_MX"
    DNS_NS = "DNS_NS"


CATEGORY_OF: dict[EvidenceReasonCode, EvidenceCategory] = {
    EvidenceReasonCode.EMAIL_DOMAIN: EvidenceCategory.IDENTITY,
    EvidenceReasonCode.PHONE: EvidenceCategory.IDENTITY,
    EvidenceReasonCode.SOCIAL_PROFILE: EvidenceCategory.IDENTITY,
    EvidenceReasonCode.TITLE: EvidenceCategory.WEBSITE,
    EvidenceReasonCode.META_DESCRIPTION: EvidenceCategory.WEBSITE,
    EvidenceReasonCode.CANONICAL_URL: EvidenceCategory.WEBSITE,
    EvidenceReasonCode.REDIRECT: EvidenceCategory.WEBSITE,
    EvidenceReasonCode.CROSS_DOMAIN_REFERENCE: EvidenceCategory.WEBSITE,
    EvidenceReasonCode.CONTENT_TEXT: EvidenceCategory.CONTENT,
    EvidenceReasonCode.CONTENT_HASH: EvidenceCategory.CONTENT,
    EvidenceReasonCode.DNS_A: EvidenceCategory.NETWORK,
    EvidenceReasonCode.DNS_AAAA: EvidenceCategory.NETWORK,
    EvidenceReasonCode.DNS_CNAME: EvidenceCategory.NETWORK,
    EvidenceReasonCode.DNS_MX: EvidenceCategory.NETWORK,
    EvidenceReasonCode.DNS_NS: EvidenceCategory.NETWORK,
}

DNS_CODE_BY_RECORD_TYPE: dict[str, EvidenceReasonCode] = {
    "A": EvidenceReasonCode.DNS_A,
    "AAAA": EvidenceReasonCode.DNS_AAAA,
    "CNAME": EvidenceReasonCode.DNS_CNAME,
    "MX": EvidenceReasonCode.DNS_MX,
    "NS": EvidenceReasonCode.DNS_NS,
}

# Documented future signals. Phase 3 does not currently collect enough factual
# data to extract these deterministically; they are intentionally NOT fabricated.
FUTURE_SIGNALS: dict[str, str] = {
    "COMPANY_NAME": "Requires parsing/NER over titles; heuristic and not deterministic yet.",
    "LEGAL_ENTITY": "Requires legal-suffix parsing over content; deferred.",
    "ADDRESS": "Requires address parsing over free text; deferred.",
    "OFFICIAL_WEBSITE_REFERENCE": (
        "A semantic refinement of CROSS_DOMAIN_REFERENCE (rel/link context); "
        "recorded as CROSS_DOMAIN_REFERENCE for now."
    ),
    "TLS_CERTIFICATE": "Phase 3 does not capture TLS certificate details; deferred.",
}
