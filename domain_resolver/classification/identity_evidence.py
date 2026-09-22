"""Identity-evidence layer (Stage 2B).

Computes *identity continuity* signals between two domains — "these may represent
the same underlying entity/operator" — from Phase 4 features. This is deliberately
separate from (a) organizational-relationship evidence (product/subsidiary/…) and
(b) the SAME_AS decision. Per the SOP, identity evidence is **supporting only**:
it can raise confidence and lift a pair out of UNRELATED into REVIEW_REQUIRED, but
it can NEVER by itself create SAME_AS — that still requires an observed redirect.

Pure: no network/DB. Symmetric (no direction).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from domain_resolver.features import normalization as norm
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.models.entities import EvidenceStrength

# A brand key must be at least this long to support a prefix match, so short or
# generic stems (e.g. "one", "co") never link unrelated domains.
_MIN_BRAND_PREFIX = 5

_ALPHA_RE = re.compile(r"[a-z]")


def _is_name(value: str) -> bool:
    """True only for a plausible entity name — rejects years and numeric junk.

    A copyright year ("2024"), a bare number, or a 1-2 letter stub must never
    link two domains as the same organization. Requires at least three alphabetic
    characters.
    """
    return len(_ALPHA_RE.findall(value)) >= 3


class IdentitySignalType(StrEnum):
    ORGANIZATION_NAME_MATCH = "ORGANIZATION_NAME_MATCH"
    BRAND_NAME_MATCH = "BRAND_NAME_MATCH"
    COPYRIGHT_OWNER_MATCH = "COPYRIGHT_OWNER_MATCH"
    SHARED_ANALYTICS_ID = "SHARED_ANALYTICS_ID"
    SHARED_GTM_ID = "SHARED_GTM_ID"
    SHARED_TLS_CERTIFICATE = "SHARED_TLS_CERTIFICATE"
    SHARED_TLS_SAN = "SHARED_TLS_SAN"
    CONTENT_FINGERPRINT_MATCH = "CONTENT_FINGERPRINT_MATCH"


@dataclass(frozen=True)
class IdentityEvidence:
    """One symmetric identity signal shared by both domains."""

    signal_type: IdentitySignalType
    strength: EvidenceStrength
    value: str


_STRONG = {EvidenceStrength.VERY_STRONG, EvidenceStrength.STRONG}


def _brand_match(keys_a: list[str], keys_b: list[str]) -> str | None:
    """Return the matched brand key if any A-key equals or prefixes a B-key."""
    for a in keys_a:
        if not _is_name(a):
            continue
        for b in keys_b:
            if not _is_name(b):
                continue
            if a == b:
                return a
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if len(shorter) >= _MIN_BRAND_PREFIX and longer.startswith(shorter):
                return shorter
    return None


def compute_identity_evidence(
    view_a: DomainFeatureView, view_b: DomainFeatureView
) -> list[IdentityEvidence]:
    fa, fb = view_a.features, view_b.features
    out: list[IdentityEvidence] = []

    # -- technical operator fingerprints (strongest) --------------------------
    if fa.tls_fingerprint and fa.tls_fingerprint == fb.tls_fingerprint:
        out.append(
            IdentityEvidence(
                IdentitySignalType.SHARED_TLS_CERTIFICATE,
                EvidenceStrength.VERY_STRONG,
                fa.tls_fingerprint,
            )
        )
    else:
        # A shared SAN, or one domain listed on the other's certificate.
        sans_a = set(fa.tls_sans)
        sans_b = set(fb.tls_sans)
        shared_san = sans_a & sans_b
        cross = {s for s in sans_a if norm.is_same_site(s, view_b.host)} | {
            s for s in sans_b if norm.is_same_site(s, view_a.host)
        }
        san_hit = sorted(shared_san | cross)
        if san_hit:
            out.append(
                IdentityEvidence(
                    IdentitySignalType.SHARED_TLS_SAN, EvidenceStrength.STRONG, san_hit[0]
                )
            )

    shared_ga = sorted(set(fa.analytics_ids) & set(fb.analytics_ids))
    if shared_ga:
        out.append(
            IdentityEvidence(
                IdentitySignalType.SHARED_ANALYTICS_ID, EvidenceStrength.STRONG, shared_ga[0]
            )
        )
    shared_gtm = sorted(set(fa.gtm_ids) & set(fb.gtm_ids))
    if shared_gtm:
        out.append(
            IdentityEvidence(
                IdentitySignalType.SHARED_GTM_ID, EvidenceStrength.STRONG, shared_gtm[0]
            )
        )

    # -- named-entity identity (SUPPORTING only) ------------------------------
    # A shared organization/copyright name is supporting, never sufficient on its
    # own: names can be embedded or coincidental (a hijacked page may quote an
    # unrelated brand, two firms may share a common word). Only a same-operator
    # fingerprint or identical content is strong enough to recover a pair from
    # UNRELATED. Years/numeric junk are excluded outright.
    shared_org = sorted(n for n in set(fa.org_names) & set(fb.org_names) if _is_name(n))
    if shared_org:
        out.append(
            IdentityEvidence(
                IdentitySignalType.ORGANIZATION_NAME_MATCH,
                EvidenceStrength.SUPPORTING,
                shared_org[0],
            )
        )
    if (
        fa.copyright_owner
        and fa.copyright_owner == fb.copyright_owner
        and _is_name(fa.copyright_owner)
    ):
        out.append(
            IdentityEvidence(
                IdentitySignalType.COPYRIGHT_OWNER_MATCH,
                EvidenceStrength.SUPPORTING,
                fa.copyright_owner,
            )
        )

    # -- content identity -----------------------------------------------------
    if (fa.content_hash and fa.content_hash == fb.content_hash) or (
        fa.text_fingerprint and fa.text_fingerprint == fb.text_fingerprint
    ):
        out.append(
            IdentityEvidence(
                IdentitySignalType.CONTENT_FINGERPRINT_MATCH, EvidenceStrength.STRONG, "content"
            )
        )

    # -- brand-name similarity (supporting only) ------------------------------
    brand = _brand_match(fa.brand_keys, fb.brand_keys)
    if brand is not None:
        out.append(
            IdentityEvidence(
                IdentitySignalType.BRAND_NAME_MATCH, EvidenceStrength.SUPPORTING, brand
            )
        )

    return out


def has_strong_identity(evidence: list[IdentityEvidence]) -> bool:
    """True if identity continuity is strong enough to justify REVIEW over UNRELATED.

    Requires at least one STRONG/VERY_STRONG signal (shared operator fingerprint,
    exact organization/copyright name, or identical content). A brand-name match
    alone (SUPPORTING) is intentionally NOT enough — a look-alike name never lifts
    a pair out of UNRELATED.
    """
    return any(e.strength in _STRONG for e in evidence)
