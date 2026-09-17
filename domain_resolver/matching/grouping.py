"""Organization-level grouping from pairwise matches.

Groups are the connected components of the graph whose edges are confident
positive matches. This means membership is transitive over confident **direct**
matches (A-B and B-C place A, B, C in one group). This is a deliberate,
documented modeling choice: the group records the direct edges that formed it, so
a reviewer can see that A-C may be *inferred through* B rather than directly
matched. No inferred A-C pair is fabricated or persisted as a direct match.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from domain_resolver.matching.matcher import MatchResult


class OrganizationGroup(BaseModel):
    domain_ids: list[UUID]
    direct_pairs: list[tuple[UUID, UUID]] = Field(default_factory=list)


def group_domains(results: list[MatchResult]) -> list[OrganizationGroup]:
    """Union confident positive matches into organization groups (components)."""
    parent: dict[UUID, UUID] = {}

    def find(node: UUID) -> UUID:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: UUID, b: UUID) -> None:
        parent[find(a)] = find(b)

    edges: list[tuple[UUID, UUID]] = []
    for result in results:
        find(result.domain_a_id)
        find(result.domain_b_id)
        if result.same_organization:
            union(result.domain_a_id, result.domain_b_id)
            pair = (
                (result.domain_a_id, result.domain_b_id)
                if result.domain_a_id < result.domain_b_id
                else (result.domain_b_id, result.domain_a_id)
            )
            edges.append(pair)

    components: dict[UUID, list[UUID]] = {}
    for node in parent:
        components.setdefault(find(node), []).append(node)

    groups: list[OrganizationGroup] = []
    for members in components.values():
        member_set = set(members)
        direct = sorted(pair for pair in edges if pair[0] in member_set and pair[1] in member_set)
        groups.append(OrganizationGroup(domain_ids=sorted(members), direct_pairs=direct))
    return sorted(groups, key=lambda g: g.domain_ids)
