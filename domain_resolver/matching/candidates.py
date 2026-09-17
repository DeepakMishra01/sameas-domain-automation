"""Candidate-pair generation.

Proposes which domain pairs are worth evaluating, so the matcher need not compare
every domain with every other. It uses cheap shared-signal co-occurrence plus
structural (redirect/canonical/reference) edges and domain-name similarity.

Candidate generation NEVER decides that two domains are the same organization —
it only narrows the set of pairs the matcher will evaluate.
"""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from uuid import UUID

from domain_resolver.features import normalization as norm
from domain_resolver.matching.config import DEFAULT_MATCHER_CONFIG, MatcherConfig
from domain_resolver.matching.views import DomainFeatureView

# A permissive threshold for *candidacy* only (the matcher applies stricter rules).
_CANDIDATE_NAME_SIMILARITY = 0.5


def generate_candidate_pairs(
    views: list[DomainFeatureView], config: MatcherConfig = DEFAULT_MATCHER_CONFIG
) -> list[tuple[DomainFeatureView, DomainFeatureView]]:
    by_id: dict[UUID, DomainFeatureView] = {view.domain_id: view for view in views}
    host_to_id: dict[str, UUID] = {view.host: view.domain_id for view in views}
    pairs: set[tuple[UUID, UUID]] = set()

    def add(a: UUID, b: UUID) -> None:
        if a != b:
            pairs.add((a, b) if a < b else (b, a))

    # Shared-signal co-occurrence via inverted indexes.
    buckets: dict[str, dict[str, list[UUID]]] = {
        "email": defaultdict(list),
        "phone": defaultdict(list),
        "social": defaultdict(list),
        "ref": defaultdict(list),
        "dns": defaultdict(list),
    }
    for view in views:
        f = view.features
        for value in f.email_domains:
            buckets["email"][value].append(view.domain_id)
        for value in f.phone_numbers:
            buckets["phone"][value].append(view.domain_id)
        for profile in f.social_profiles:
            buckets["social"][profile.url].append(view.domain_id)
        for value in f.referenced_domains:
            buckets["ref"][value].append(view.domain_id)
        for value in [*f.dns_a, *f.dns_ns, *f.dns_mx]:
            buckets["dns"][value].append(view.domain_id)

    for index in buckets.values():
        for ids in index.values():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    add(ids[i], ids[j])

    # Structural edges: a domain that redirects/canonicalizes/references another
    # observed domain is a candidate pair with it.
    for view in views:
        f = view.features
        for target in (f.redirect_target_domain, f.final_domain, f.canonical_domain):
            other = _resolve_host(target, host_to_id)
            if other is not None:
                add(view.domain_id, other)
        for referenced in f.referenced_domains:
            other = _resolve_host(referenced, host_to_id)
            if other is not None:
                add(view.domain_id, other)

    # Domain-name similarity (n is small per company).
    for i in range(len(views)):
        for j in range(i + 1, len(views)):
            ratio = SequenceMatcher(
                None,
                norm.domain_name_key(views[i].host),
                norm.domain_name_key(views[j].host),
            ).ratio()
            if ratio >= _CANDIDATE_NAME_SIMILARITY:
                add(views[i].domain_id, views[j].domain_id)

    return [(by_id[a], by_id[b]) for a, b in sorted(pairs)]


def _resolve_host(target: str | None, host_to_id: dict[str, UUID]) -> UUID | None:
    if target is None:
        return None
    if target in host_to_id:
        return host_to_id[target]
    for host, domain_id in host_to_id.items():
        if norm.is_same_site(target, host):
            return domain_id
    return None
