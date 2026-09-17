"""Deterministic pairwise feature computation for a candidate domain pair.

Given two domains' Phase 4 features, produce the set of explainable signals
(reason codes) that fire, with the values that caused each. This module makes no
same-organization decision — it only describes the factual/derived overlap.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from domain_resolver.features import normalization as norm
from domain_resolver.matching.config import MatcherConfig
from domain_resolver.matching.reason_codes import MatchReasonCode
from domain_resolver.matching.views import DomainFeatureView


class PairwiseSignal(BaseModel):
    code: MatchReasonCode
    detail: dict[str, object] = Field(default_factory=dict)


class PairwiseFeatureSet(BaseModel):
    """All signals that fired for a pair, plus a stored audit view."""

    signals: list[PairwiseSignal] = Field(default_factory=list)
    audit: dict[str, object] = Field(default_factory=dict)

    def codes(self) -> list[MatchReasonCode]:
        return [signal.code for signal in self.signals]


def _matches_host(target: str | None, host: str) -> bool:
    return target is not None and (target == host or norm.is_same_site(target, host))


def _references(referenced: list[str], host: str) -> list[str]:
    return [ref for ref in referenced if ref == host or norm.is_same_site(ref, host)]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _tokens(text: str | None) -> set[str]:
    return set(norm.tokenize(text)) if text else set()


def build_pairwise_features(
    view_a: DomainFeatureView, view_b: DomainFeatureView, config: MatcherConfig
) -> PairwiseFeatureSet:
    fa, fb = view_a.features, view_b.features
    host_a, host_b = view_a.host, view_b.host
    signals: list[PairwiseSignal] = []
    audit: dict[str, object] = {}

    def fire(code: MatchReasonCode, **detail: object) -> None:
        signals.append(PairwiseSignal(code=code, detail=detail))

    # -- structural links -----------------------------------------------------
    redirect_ab = fa.has_redirect and (
        _matches_host(fa.redirect_target_domain, host_b) or _matches_host(fa.final_domain, host_b)
    )
    redirect_ba = fb.has_redirect and (
        _matches_host(fb.redirect_target_domain, host_a) or _matches_host(fb.final_domain, host_a)
    )
    if redirect_ab or redirect_ba:
        fire(MatchReasonCode.REDIRECT, a_to_b=redirect_ab, b_to_a=redirect_ba)

    canonical = _matches_host(fa.canonical_domain, host_b) or _matches_host(
        fb.canonical_domain, host_a
    )
    if canonical:
        fire(
            MatchReasonCode.CANONICAL_URL,
            a_canonical=fa.canonical_domain,
            b_canonical=fb.canonical_domain,
        )

    ref_ab = bool(_references(fa.referenced_domains, host_b))
    ref_ba = bool(_references(fb.referenced_domains, host_a))
    if ref_ab and ref_ba:
        fire(MatchReasonCode.CROSS_DOMAIN_REFERENCE_MUTUAL, a_to_b=True, b_to_a=True)
    elif ref_ab or ref_ba:
        fire(MatchReasonCode.CROSS_DOMAIN_REFERENCE, a_to_b=ref_ab, b_to_a=ref_ba)

    # -- shared identity ------------------------------------------------------
    shared_emails = sorted(set(fa.email_domains) & set(fb.email_domains))
    if shared_emails:
        fire(MatchReasonCode.SAME_EMAIL_DOMAIN, shared=shared_emails)

    shared_phones = sorted(set(fa.phone_numbers) & set(fb.phone_numbers))
    if shared_phones:
        fire(MatchReasonCode.SAME_PHONE, shared=shared_phones)

    socials_a = {p.url for p in fa.social_profiles}
    socials_b = {p.url for p in fb.social_profiles}
    shared_social = sorted(socials_a & socials_b)
    if shared_social:
        fire(MatchReasonCode.SAME_SOCIAL_PROFILE, shared=shared_social)

    # -- content / network similarity ----------------------------------------
    if fa.content_hash and fa.content_hash == fb.content_hash:
        fire(MatchReasonCode.CONTENT_FINGERPRINT_MATCH, hash=fa.content_hash)
    elif fa.text_fingerprint and fa.text_fingerprint == fb.text_fingerprint:
        fire(MatchReasonCode.CONTENT_FINGERPRINT_MATCH, fingerprint=fa.text_fingerprint)

    title_sim = _jaccard(_tokens(fa.normalized_title), _tokens(fb.normalized_title))
    audit["title_similarity"] = title_sim
    if title_sim >= config.title_similarity_threshold:
        fire(MatchReasonCode.SIMILAR_TITLE, similarity=title_sim)

    meta_sim = _jaccard(
        _tokens(fa.normalized_meta_description), _tokens(fb.normalized_meta_description)
    )
    audit["meta_similarity"] = meta_sim
    if meta_sim >= config.meta_similarity_threshold:
        fire(MatchReasonCode.SIMILAR_META, similarity=meta_sim)

    content_sim = _jaccard(set(fa.text_tokens), set(fb.text_tokens))
    audit["content_similarity"] = content_sim
    if content_sim >= config.content_similarity_threshold:
        fire(MatchReasonCode.SIMILAR_CONTENT, similarity=content_sim)

    shared_refs = sorted(
        (set(fa.referenced_domains) & set(fb.referenced_domains)) - {host_a, host_b}
    )
    if shared_refs:
        fire(MatchReasonCode.SHARED_REFERENCED_DOMAINS, shared=shared_refs)

    dns_overlap = sorted(
        (set(fa.dns_a) & set(fb.dns_a))
        | (set(fa.dns_ns) & set(fb.dns_ns))
        | (set(fa.dns_mx) & set(fb.dns_mx))
    )
    if dns_overlap:
        fire(MatchReasonCode.DNS_OVERLAP, shared=dns_overlap)

    name_sim = SequenceMatcher(
        None, norm.domain_name_key(host_a), norm.domain_name_key(host_b)
    ).ratio()
    audit["domain_name_similarity"] = name_sim
    if name_sim >= config.domain_name_similarity_threshold:
        fire(MatchReasonCode.DOMAIN_NAME_SIMILARITY, similarity=name_sim)

    # -- contradictions -------------------------------------------------------
    if fa.email_domains and fb.email_domains and not shared_emails:
        fire(
            MatchReasonCode.DIFFERENT_EMAIL_DOMAIN,
            a=sorted(fa.email_domains),
            b=sorted(fb.email_domains),
        )
    if fa.phone_numbers and fb.phone_numbers and not shared_phones:
        fire(
            MatchReasonCode.DIFFERENT_PHONE,
            a=sorted(fa.phone_numbers),
            b=sorted(fb.phone_numbers),
        )

    return PairwiseFeatureSet(signals=signals, audit=audit)
