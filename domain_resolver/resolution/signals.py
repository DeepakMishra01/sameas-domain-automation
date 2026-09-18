"""Deterministic directional primary-domain signals from Phase 4 features.

For a same-organization group, compute which domains are pointed *to* (evidence
of being primary) and which point *away* to a peer (evidence of being secondary),
plus conflicts (mutual pointing). Pure: no network/DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from domain_resolver.features import normalization as norm
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.resolution.reason_codes import PrimaryReasonCode


@dataclass
class SignalSource:
    """Where a signal came from — used to fetch supporting evidence."""

    observation_id: UUID
    peer_host: str | None = None
    peer_domain_id: UUID | None = None


@dataclass
class DomainSignals:
    domain_id: UUID
    host: str
    observation_id: UUID
    positive: dict[PrimaryReasonCode, list[SignalSource]] = field(default_factory=dict)
    negative: dict[PrimaryReasonCode, list[SignalSource]] = field(default_factory=dict)

    def add_positive(self, code: PrimaryReasonCode, source: SignalSource) -> None:
        self.positive.setdefault(code, []).append(source)

    def add_negative(self, code: PrimaryReasonCode, source: SignalSource) -> None:
        self.negative.setdefault(code, []).append(source)


@dataclass
class GroupSignals:
    signals: dict[UUID, DomainSignals]
    conflicts: list[dict[str, object]] = field(default_factory=list)


def _matches(target: str | None, host: str) -> bool:
    return target is not None and (target == host or norm.is_same_site(target, host))


def _redirects_to(view: DomainFeatureView, peer_host: str) -> bool:
    f = view.features
    return f.has_redirect and (
        _matches(f.redirect_target_domain, peer_host) or _matches(f.final_domain, peer_host)
    )


def _canonical_to(view: DomainFeatureView, peer_host: str) -> bool:
    return _matches(view.features.canonical_domain, peer_host)


def compute_group_signals(views: list[DomainFeatureView]) -> GroupSignals:
    signals: dict[UUID, DomainSignals] = {
        v.domain_id: DomainSignals(
            domain_id=v.domain_id, host=v.host, observation_id=v.observation_id
        )
        for v in views
    }
    directed: set[tuple[UUID, UUID]] = set()  # (source, target) redirect/canonical edges

    for source in views:
        redirects_away = False
        for target in views:
            if source.domain_id == target.domain_id:
                continue
            src = SignalSource(
                observation_id=source.observation_id,
                peer_host=source.host,
                peer_domain_id=source.domain_id,
            )
            if _redirects_to(source, target.host):
                redirects_away = True
                directed.add((source.domain_id, target.domain_id))
                signals[source.domain_id].add_negative(
                    PrimaryReasonCode.REDIRECTS_AWAY,
                    SignalSource(source.observation_id, target.host, target.domain_id),
                )
                signals[target.domain_id].add_positive(PrimaryReasonCode.REDIRECT_TARGET, src)
            if _canonical_to(source, target.host):
                directed.add((source.domain_id, target.domain_id))
                signals[source.domain_id].add_negative(
                    PrimaryReasonCode.CANONICAL_AWAY,
                    SignalSource(source.observation_id, target.host, target.domain_id),
                )
                signals[target.domain_id].add_positive(PrimaryReasonCode.CANONICAL_TARGET, src)

        # Self / own-site signals.
        f = source.features
        own = SignalSource(observation_id=source.observation_id)
        if _matches(f.canonical_domain, source.host):
            signals[source.domain_id].add_positive(PrimaryReasonCode.SELF_CANONICAL, own)
        has_content = bool(f.normalized_title or f.normalized_text_excerpt)
        if has_content and not redirects_away:
            signals[source.domain_id].add_positive(PrimaryReasonCode.ACTIVE_WEBSITE, own)

    # Cross-domain reference direction. A link from A to B is weak evidence that B
    # is primary. A *one-way* link (A links to B, B does not link back) is
    # directional — B is referenced and A defers — so A is dampened. A *mutual*
    # reference is neutral (both get the weak positive, no away signal), keeping
    # genuinely co-equal sites ambiguous.
    ref_edges: dict[tuple[UUID, UUID], tuple[DomainFeatureView, DomainFeatureView]] = {}
    for referrer in views:
        for referenced in views:
            if referrer.domain_id == referenced.domain_id:
                continue
            if any(_matches(r, referenced.host) for r in referrer.features.referenced_domains):
                ref_edges[(referrer.domain_id, referenced.domain_id)] = (referrer, referenced)
    for (referrer_id, referenced_id), (referrer, referenced) in ref_edges.items():
        signals[referenced_id].add_positive(
            PrimaryReasonCode.REFERENCED_BY_PEER,
            SignalSource(referrer.observation_id, referrer.host, referrer.domain_id),
        )
        if (referenced_id, referrer_id) not in ref_edges:  # one-way: referrer defers
            signals[referrer_id].add_negative(
                PrimaryReasonCode.REFERENCES_AWAY,
                SignalSource(referrer.observation_id, referenced.host, referenced.domain_id),
            )

    conflicts: list[dict[str, object]] = []
    for src_id, tgt_id in directed:
        if (tgt_id, src_id) in directed and src_id < tgt_id:
            conflicts.append(
                {"type": "MUTUAL_DIRECTION", "domain_a": str(src_id), "domain_b": str(tgt_id)}
            )

    return GroupSignals(signals=signals, conflicts=conflicts)
