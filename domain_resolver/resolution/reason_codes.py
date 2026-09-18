"""Primary-domain reason codes and their polarity.

A reason code names a deterministic, directional signal derived from Phase 4
features: which domain other group members point *to* (evidence of being
primary) versus which domain points *away* to a peer (evidence of being
secondary). None of these are name/age/TLD/popularity assumptions.
"""

from __future__ import annotations

from enum import StrEnum


class PrimaryReasonCode(StrEnum):
    # Positive: evidence that THIS domain is the primary/canonical destination
    REDIRECT_TARGET = "REDIRECT_TARGET"  # a peer redirects to this domain
    CANONICAL_TARGET = "CANONICAL_TARGET"  # a peer declares canonical = this domain
    SELF_CANONICAL = "SELF_CANONICAL"  # this domain declares itself canonical
    ACTIVE_WEBSITE = "ACTIVE_WEBSITE"  # serves its own content and does not defer
    REFERENCED_BY_PEER = "REFERENCED_BY_PEER"  # a peer links to this domain

    # Negative: evidence that THIS domain defers to a peer (i.e. is secondary)
    REDIRECTS_AWAY = "REDIRECTS_AWAY"  # this domain redirects to a peer
    CANONICAL_AWAY = "CANONICAL_AWAY"  # this domain's canonical is a peer


NEGATIVE_CODES: frozenset[PrimaryReasonCode] = frozenset(
    {PrimaryReasonCode.REDIRECTS_AWAY, PrimaryReasonCode.CANONICAL_AWAY}
)

POSITIVE_CODES: frozenset[PrimaryReasonCode] = frozenset(
    code for code in PrimaryReasonCode if code not in NEGATIVE_CODES
)
