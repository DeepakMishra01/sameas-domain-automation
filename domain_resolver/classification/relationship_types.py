"""Relationship taxonomy enums.

These are the business-level relationship categories the classifier assigns to a
domain pair, plus the PART_OF subtype and the edge direction. Values match the
CPT SOP and use the project's ``StrEnum`` convention (see
``domain_resolver.models.entities``).
"""

from __future__ import annotations

from enum import StrEnum


class RelationshipType(StrEnum):
    """The type of relationship between two domains.

    SAME_AS is reserved for the *same entity/identity* and requires an observed
    redirect (or a corroborated canonical). PART_OF and ACQUIRED keep the two
    domains as *distinct* identities. REVIEW_REQUIRED is the safe default when a
    relationship exists but its type cannot be determined; UNRELATED when there
    is no credible relationship.
    """

    SAME_AS = "SAME_AS"
    PART_OF = "PART_OF"
    ACQUIRED = "ACQUIRED"
    UNRELATED = "UNRELATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class PartOfSubtype(StrEnum):
    """The organizational nature of a PART_OF relationship, when determinable."""

    PRODUCT = "PRODUCT"
    BRAND = "BRAND"
    SUBSIDIARY = "SUBSIDIARY"
    BUSINESS_UNIT = "BUSINESS_UNIT"
    SERVICE = "SERVICE"
    DIVISION = "DIVISION"
    REGIONAL_ENTITY = "REGIONAL_ENTITY"
    OTHER = "OTHER"


class RelationshipDirection(StrEnum):
    """Orientation of a directed relationship over a canonical pair (a < b).

    The direction always points from the *subordinate* domain (secondary /
    part-of / acquired) to the *superior* domain (primary / parent / acquirer).
    """

    A_TO_B = "A_TO_B"  # domain_a is subordinate; domain_b is superior/primary
    B_TO_A = "B_TO_A"  # domain_b is subordinate; domain_a is superior/primary
    SYMMETRIC = "SYMMETRIC"  # mutual/contradictory pointing (e.g. two-way redirect)
    UNDETERMINED = "UNDETERMINED"  # no directional evidence
