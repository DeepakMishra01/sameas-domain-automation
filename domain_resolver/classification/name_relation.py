"""Deterministic same-brand / regional-variant detection from domain names.

For CPT candidate pairs (already believed related), two very common patterns are
safely typable from the registrable names alone, without reading the page:

- **Same registrable name, different TLD** — ``febino.in`` / ``febino.com`` — the
  same brand operating under two TLDs (a regional variant).
- **One name contains the other's full brand plus a qualifier** —
  ``carsforstars-brighton.co.uk`` / ``carsforstars.net`` — a regional/branch site
  of the parent brand.

Both map to PART_OF (subtype REGIONAL_ENTITY). This is deliberately high-precision:
the shared core must be specific (not a generic business word, >= 5 chars) and the
containment must cover the shorter name's *entire* token sequence — so
``guardianvoices`` vs ``theguardian`` does NOT match. Pure: no network/DB.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_resolver.classification.reason_codes import ClassificationReasonCode
from domain_resolver.classification.relationship_types import PartOfSubtype
from domain_resolver.features import normalization as norm
from domain_resolver.matching.views import DomainFeatureView

# Registrable-domain second-level suffixes (so co.uk / com.au resolve correctly).
_SECOND_LEVEL = frozenset({"co", "com", "net", "org", "gov", "edu", "ac", "or", "ne", "gob"})
# Global (non-country) TLDs preferred as the parent when direction is otherwise a tie.
_GLOBAL_TLDS = frozenset({"com", "net", "org", "io", "ai", "co", "app", "dev", "inc"})
# Generic words that must never link two brands on their own.
_GENERIC = frozenset(
    {
        "solutions",
        "services",
        "security",
        "digital",
        "technologies",
        "technology",
        "group",
        "global",
        "systems",
        "consulting",
        "online",
        "media",
        "studio",
        "software",
        "world",
        "india",
        "care",
        "health",
        "company",
        "agency",
        "network",
    }
)


@dataclass(frozen=True)
class NameRelation:
    parent: DomainFeatureView
    child: DomainFeatureView
    subtype: PartOfSubtype
    reason_code: ClassificationReasonCode


def registrable_name(host: str) -> str:
    """Return the registrable label of a host (handles co.uk / com.au style TLDs)."""
    parts = host.lower().rstrip(".").split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0]


def _specific(core: str, tokens: list[str]) -> bool:
    return len(core) >= 5 and not any(t in _GENERIC for t in tokens)


def _tld(host: str) -> str:
    return host.lower().rstrip(".").rsplit(".", 1)[-1]


def _pick_parent(
    a: DomainFeatureView, b: DomainFeatureView
) -> tuple[DomainFeatureView, DomainFeatureView]:
    """Choose parent/child for two co-equal same-name domains, deterministically."""
    a_to_b = any(norm.is_same_site(r, b.host) for r in a.features.referenced_domains)
    b_to_a = any(norm.is_same_site(r, a.host) for r in b.features.referenced_domains)
    if a_to_b and not b_to_a:  # a defers to b -> b is parent
        return b, a
    if b_to_a and not a_to_b:
        return a, b
    a_global = _tld(a.host) in _GLOBAL_TLDS
    b_global = _tld(b.host) in _GLOBAL_TLDS
    if a_global and not b_global:
        return a, b
    if b_global and not a_global:
        return b, a
    return (a, b) if a.host < b.host else (b, a)  # stable fallback


def detect_name_relation(
    view_a: DomainFeatureView, view_b: DomainFeatureView
) -> NameRelation | None:
    name_a = registrable_name(view_a.host)
    name_b = registrable_name(view_b.host)
    tokens_a = norm.tokenize(name_a)
    tokens_b = norm.tokenize(name_b)
    if not tokens_a or not tokens_b:
        return None
    core_a = "".join(tokens_a)
    core_b = "".join(tokens_b)

    # Same registrable name, different TLD -> regional variant of one brand.
    if core_a == core_b and _specific(core_a, tokens_a):
        if _tld(view_a.host) != _tld(view_b.host):
            parent, child = _pick_parent(view_a, view_b)
            return NameRelation(
                parent,
                child,
                PartOfSubtype.REGIONAL_ENTITY,
                ClassificationReasonCode.SAME_NAME_DIFFERENT_TLD,
            )
        return None

    # One name contains the other's FULL brand as a leading qualifier -> branch.
    short, long_, sview, lview = (
        (tokens_a, tokens_b, view_a, view_b)
        if len(tokens_a) < len(tokens_b)
        else (tokens_b, tokens_a, view_b, view_a)
    )
    if len(long_) > len(short) and long_[: len(short)] == short:
        core_short = "".join(short)
        if _specific(core_short, short):
            return NameRelation(
                sview,
                lview,
                PartOfSubtype.REGIONAL_ENTITY,
                ClassificationReasonCode.BRAND_PREFIX_VARIANT,
            )
    return None
