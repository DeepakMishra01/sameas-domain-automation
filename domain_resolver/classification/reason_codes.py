"""Explainable reason codes for relationship classification.

Each code names the deterministic signal that drove a classification. They are
grouped by the relationship type they support and are stored alongside the
decision for audit. Codes are never hard-coded to any company.
"""

from __future__ import annotations

from enum import StrEnum


class ClassificationReasonCode(StrEnum):
    # -- SAME_AS (an observed redirect is the ONLY sufficient signal) ---------
    REDIRECT_TO_PRIMARY = "REDIRECT_TO_PRIMARY"  # direct redirect to the peer
    REDIRECT_CHAIN_TO_PRIMARY = "REDIRECT_CHAIN_TO_PRIMARY"  # multi-hop redirect ends at peer
    COMMON_REDIRECT_TARGET = "COMMON_REDIRECT_TARGET"  # both domains redirect to the same domain

    # -- PART_OF (explicit on-page statement of a component relationship) ------
    PRODUCT_OF = "PRODUCT_OF"
    BRAND_OF = "BRAND_OF"
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    BUSINESS_UNIT_OF = "BUSINESS_UNIT_OF"
    SERVICE_OF = "SERVICE_OF"
    DIVISION_OF = "DIVISION_OF"
    REGIONAL_ENTITY_OF = "REGIONAL_ENTITY_OF"
    PART_OF_STATEMENT = "PART_OF_STATEMENT"  # generic "part of" / "operated by"
    SAME_NAME_DIFFERENT_TLD = "SAME_NAME_DIFFERENT_TLD"  # febino.in / febino.com (regional variant)
    BRAND_PREFIX_VARIANT = "BRAND_PREFIX_VARIANT"  # carsforstars-brighton / carsforstars (branch)
    CANONICAL_TO_PARENT = "CANONICAL_TO_PARENT"  # A's canonical is B (differ) -> A is part of B
    SHARED_BRAND_IDENTITY = "SHARED_BRAND_IDENTITY"  # same brand/org name across the two domains
    ASSUMED_RELATED = "ASSUMED_RELATED"  # CPT candidate, no strong signal -> assumed part-of

    # -- ACQUIRED (explicit on-page acquisition statement) --------------------
    ACQUIRED_BY = "ACQUIRED_BY"  # this domain's page states it was acquired by the peer
    ACQUISITION_ANNOUNCEMENT = "ACQUISITION_ANNOUNCEMENT"  # this domain announces acquiring peer

    # -- REVIEW_REQUIRED (a relationship exists but its type is undetermined) --
    RELATED_TYPE_UNDETERMINED = "RELATED_TYPE_UNDETERMINED"  # matcher relates them, no typing sig
    MUTUAL_REDIRECT_CONFLICT = "MUTUAL_REDIRECT_CONFLICT"  # each redirects to the other
    CANONICAL_WITHOUT_REDIRECT = (
        "CANONICAL_WITHOUT_REDIRECT"  # canonical to peer with identical content: needs a redirect
    )
    CONTRADICTORY_TYPE_SIGNALS = "CONTRADICTORY_TYPE_SIGNALS"  # conflicting typing statements
    IDENTITY_WITHOUT_REDIRECT = (
        "IDENTITY_WITHOUT_REDIRECT"  # strong identity evidence but no redirect: needs review
    )

    # -- UNRELATED ------------------------------------------------------------
    NO_CREDIBLE_RELATIONSHIP = "NO_CREDIBLE_RELATIONSHIP"
    PARKED_OR_HOSTING_PAGE = (
        "PARKED_OR_HOSTING_PAGE"  # parked/for-sale/broker/host placeholder: shared host, not a biz
    )


SAME_AS_CODES: frozenset[ClassificationReasonCode] = frozenset(
    {
        ClassificationReasonCode.REDIRECT_TO_PRIMARY,
        ClassificationReasonCode.REDIRECT_CHAIN_TO_PRIMARY,
    }
)

PART_OF_CODES: frozenset[ClassificationReasonCode] = frozenset(
    {
        ClassificationReasonCode.PRODUCT_OF,
        ClassificationReasonCode.BRAND_OF,
        ClassificationReasonCode.SUBSIDIARY_OF,
        ClassificationReasonCode.BUSINESS_UNIT_OF,
        ClassificationReasonCode.SERVICE_OF,
        ClassificationReasonCode.DIVISION_OF,
        ClassificationReasonCode.REGIONAL_ENTITY_OF,
        ClassificationReasonCode.PART_OF_STATEMENT,
        ClassificationReasonCode.SAME_NAME_DIFFERENT_TLD,
        ClassificationReasonCode.BRAND_PREFIX_VARIANT,
        ClassificationReasonCode.CANONICAL_TO_PARENT,
        ClassificationReasonCode.SHARED_BRAND_IDENTITY,
        ClassificationReasonCode.ASSUMED_RELATED,
    }
)

ACQUIRED_CODES: frozenset[ClassificationReasonCode] = frozenset(
    {
        ClassificationReasonCode.ACQUIRED_BY,
        ClassificationReasonCode.ACQUISITION_ANNOUNCEMENT,
    }
)
