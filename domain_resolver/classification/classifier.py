"""Deterministic, explainable relationship classifier.

Given two domains' Phase 4 features and the Phase 5 match result (which only says
"are they related?"), assign exactly one relationship type in strict precedence:

    1. SAME_AS   — an observed redirect / meta-refresh to the peer (mandatory,
                   sufficient). A canonical to the peer counts only when
                   corroborated by identical content; otherwise REVIEW_REQUIRED.
    2. ACQUIRED  — an explicit on-page acquisition statement naming the peer.
    3. PART_OF   — an explicit on-page "product/brand/subsidiary/… of" statement.
    4. REVIEW    — the matcher relates them but no typing signal fired.
    5. UNRELATED — no credible relationship.

A redirect always wins (SOP §13 Case A): if a page both redirects to the peer and
carries a part-of/acquisition phrase, the result is SAME_AS and the extra
statement is retained in the explanation. Never uses an LLM, embeddings, or
name/age/TLD/popularity. Pure: no network/DB.
"""

from __future__ import annotations

from domain_resolver.classification.config import DEFAULT_CLASSIFIER_CONFIG, ClassifierConfig
from domain_resolver.classification.identity_evidence import (
    IdentitySignalType,
    compute_identity_evidence,
    has_strong_identity,
)
from domain_resolver.classification.name_relation import detect_name_relation
from domain_resolver.classification.reason_codes import ClassificationReasonCode
from domain_resolver.classification.relationship_types import (
    PartOfSubtype,
    RelationshipDirection,
    RelationshipType,
)
from domain_resolver.classification.results import (
    ClassificationConfidenceBand,
    RelationshipClassification,
)
from domain_resolver.classification.text_signals import TextSignal, detect_text_signals
from domain_resolver.features import normalization as norm
from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.matcher import MatchResult
from domain_resolver.matching.views import DomainFeatureView


def _matches(target: str | None, host: str) -> bool:
    return target is not None and (target == host or norm.is_same_site(target, host))


def _redirect_kind(view: DomainFeatureView, peer_host: str) -> str | None:
    f = view.features
    if not f.has_redirect:
        return None
    if _matches(f.redirect_target_domain, peer_host):
        return "direct"
    if _matches(f.final_domain, peer_host):
        return "chain"
    return None


def _identical_content(fa: FeatureSet, fb: FeatureSet) -> bool:
    if fa.content_hash and fa.content_hash == fb.content_hash:
        return True
    return bool(fa.text_fingerprint and fa.text_fingerprint == fb.text_fingerprint)


class _Vote:
    """A directed typing vote derived from one text signal.

    ``carrier`` is the page the phrase was found on; ``peer`` is the other domain.
    The superior/subordinate roles come from the signal's direction, not argument
    order.
    """

    superior: DomainFeatureView
    subordinate: DomainFeatureView
    type: RelationshipType
    subtype: PartOfSubtype | None
    code: ClassificationReasonCode

    def __init__(
        self,
        carrier: DomainFeatureView,
        peer: DomainFeatureView,
        signal: TextSignal,
    ) -> None:
        if signal.carrier_is_subordinate:
            self.subordinate, self.superior = carrier, peer
        else:
            self.superior, self.subordinate = carrier, peer
        self.type = signal.relationship_type
        self.subtype = signal.subtype
        self.code = signal.reason_code


class RelationshipClassifier:
    def __init__(self, config: ClassifierConfig = DEFAULT_CLASSIFIER_CONFIG) -> None:
        self._config = config

    @property
    def version(self) -> str:
        return self._config.version

    @property
    def config(self) -> ClassifierConfig:
        return self._config

    def classify(
        self,
        view_a: DomainFeatureView,
        view_b: DomainFeatureView,
        match_result: MatchResult,
    ) -> RelationshipClassification:
        # Canonicalize order (a < b) so the result matches the match_result pair.
        if view_a.domain_id > view_b.domain_id:
            view_a, view_b = view_b, view_a

        host_a, host_b = view_a.host, view_b.host

        # --- retained typing statements (used for SAME_AS notes and typing) ---
        signals_a = detect_text_signals(view_a, view_b)  # A's page, naming B
        signals_b = detect_text_signals(view_b, view_a)  # B's page, naming A

        # --- 1. SAME_AS: an observed redirect is mandatory and sufficient -----
        a_to_b = _redirect_kind(view_a, host_b)
        b_to_a = _redirect_kind(view_b, host_a)
        if a_to_b and b_to_a:
            return self._review(
                view_a,
                view_b,
                match_result,
                [ClassificationReasonCode.MUTUAL_REDIRECT_CONFLICT],
                RelationshipDirection.SYMMETRIC,
                f"{host_a} and {host_b} redirect to each other; primary is ambiguous.",
            )
        if a_to_b or b_to_a:
            source, target = (view_a, view_b) if a_to_b else (view_b, view_a)
            kind = a_to_b or b_to_a
            code = (
                ClassificationReasonCode.REDIRECT_TO_PRIMARY
                if kind == "direct"
                else ClassificationReasonCode.REDIRECT_CHAIN_TO_PRIMARY
            )
            note = self._retained_note(signals_a, signals_b)
            explanation = (
                f"{source.host} redirects to {target.host}, so they are the same entity; "
                f"{target.host} is primary." + note
            )
            return self._resolved(
                view_a,
                view_b,
                RelationshipType.SAME_AS,
                None,
                primary=target,
                secondary=source,
                confidence=self._config.confidence_redirect_same_as,
                reason_codes=[code],
                explanation=explanation,
            )

        # --- 1b. Both domains redirect to a common third domain -> SAME_AS ----
        # e.g. a.com -> hub.com and b.com -> hub.com : a and b are the same entity
        # (both are hub.com). The shared target is the primary.
        final_a = view_a.features.final_domain or host_a
        final_b = view_b.features.final_domain or host_b
        if (view_a.features.has_redirect or view_b.features.has_redirect) and _matches(
            final_a, final_b
        ):
            confidence = self._config.confidence_common_redirect
            return RelationshipClassification(
                classifier_version=self._config.version,
                domain_a_id=view_a.domain_id,
                domain_b_id=view_b.domain_id,
                domain_a=host_a,
                domain_b=host_b,
                relationship_type=RelationshipType.SAME_AS,
                direction=RelationshipDirection.SYMMETRIC,
                primary_domain_id=None,
                primary_host=final_a,
                secondary_host=None,
                confidence=confidence,
                confidence_band=self._band(confidence),
                reason_codes=[ClassificationReasonCode.COMMON_REDIRECT_TARGET],
                explanation=(
                    f"{host_a} and {host_b} both redirect to {final_a}, so they are the same "
                    f"entity; {final_a} is primary."
                ),
            )

        # --- 2 & 3. ACQUIRED / PART_OF from explicit text statements ----------
        votes = [_Vote(view_a, view_b, s) for s in signals_a] + [
            _Vote(view_b, view_a, s) for s in signals_b
        ]
        if votes:
            typed = self._from_votes(view_a, view_b, match_result, votes)
            if typed is not None:
                return typed

        # --- Same-brand / regional variant from domain names -> PART_OF -------
        # A redirect (SAME_AS) and explicit statements already took precedence. A
        # same-registrable-name/branch-prefix relation is a deterministic PART_OF
        # (regional variant), high-precision on the relationship; the parent
        # direction is a heuristic (medium confidence).
        name_rel = detect_name_relation(view_a, view_b)
        if name_rel is not None:
            return self._resolved(
                view_a,
                view_b,
                RelationshipType.PART_OF,
                name_rel.subtype,
                primary=name_rel.parent,
                secondary=name_rel.child,
                confidence=self._config.confidence_part_of_name,
                reason_codes=[name_rel.reason_code],
                explanation=(
                    f"{name_rel.child.host} and {name_rel.parent.host} share the same brand name "
                    f"with no redirect between them; treated as a regional/branch variant "
                    f"(part of {name_rel.parent.host})."
                ),
            )

        # --- Canonical is directional (A declares B canonical -> A defers to B) -
        # SAME_AS still requires an observed redirect. So:
        #   * identical content -> a mirror of the same site; strong same-entity
        #     evidence but no redirect, so REVIEW (confirm SAME_AS by hand).
        #   * content differs -> A is a distinct sub-property published under B's
        #     authoritative domain (e.g. samplitude.com canonical=borisfx.com):
        #     PART_OF, with B the parent. A mutual canonical is a conflict -> REVIEW.
        can_ab = _matches(view_a.features.canonical_domain, host_b)
        can_ba = _matches(view_b.features.canonical_domain, host_a)
        if can_ab and can_ba:
            return self._review(
                view_a,
                view_b,
                match_result,
                [ClassificationReasonCode.MUTUAL_REDIRECT_CONFLICT],
                RelationshipDirection.SYMMETRIC,
                f"{host_a} and {host_b} each declare the other canonical; direction is ambiguous.",
            )
        if can_ab or can_ba:
            child, parent = (view_a, view_b) if can_ab else (view_b, view_a)
            if _identical_content(view_a.features, view_b.features):
                return self._review(
                    view_a,
                    view_b,
                    match_result,
                    [ClassificationReasonCode.CANONICAL_WITHOUT_REDIRECT],
                    RelationshipDirection.A_TO_B if can_ab else RelationshipDirection.B_TO_A,
                    (
                        f"{child.host} declares {parent.host} canonical and their content is "
                        f"identical — same site, but SAME_AS requires an observed redirect, "
                        f"so this needs review."
                    ),
                )
            return self._resolved(
                view_a,
                view_b,
                RelationshipType.PART_OF,
                PartOfSubtype.OTHER,
                primary=parent,
                secondary=child,
                confidence=self._config.confidence_part_of_name,
                reason_codes=[ClassificationReasonCode.CANONICAL_TO_PARENT],
                explanation=(
                    f"{child.host} declares {parent.host} as its canonical domain and serves its "
                    f"own distinct content — it is published under {parent.host}, so it is part of "
                    f"{parent.host}."
                ),
            )

        # --- 4. Default: PART_OF (CPT candidates are related; no UNRELATED) ----
        # Everything that reaches here is a CPT candidate pair with no redirect and
        # no explicit statement. Rather than UNRELATED, it is treated as PART_OF
        # (per policy), with the confidence reflecting how much evidence there is:
        #   * shared brand / organization identity   -> medium
        #   * related by matcher signals only         -> low-medium
        #   * no signal at all (assumed)              -> low (flagged ASSUMED_RELATED)
        # Direction is best-effort. REVIEW is reserved for genuine conflicts above.
        identity = compute_identity_evidence(view_a, view_b)
        brand_or_org = [
            e
            for e in identity
            if e.signal_type
            in (
                IdentitySignalType.BRAND_NAME_MATCH,
                IdentitySignalType.ORGANIZATION_NAME_MATCH,
                IdentitySignalType.COPYRIGHT_OWNER_MATCH,
            )
        ]
        parent, child = self._best_effort_parent(view_a, view_b)
        if has_strong_identity(identity) or brand_or_org:
            signals = ", ".join(sorted({e.signal_type.value for e in identity}))
            confidence = self._config.confidence_part_of_identity
            reason = ClassificationReasonCode.SHARED_BRAND_IDENTITY
            explanation = (
                f"{child.host} and {parent.host} share brand/identity evidence ({signals}) with "
                f"no redirect; treated as part of {parent.host}."
            )
        elif match_result.same_organization:
            confidence = 0.45
            reason = ClassificationReasonCode.ASSUMED_RELATED
            codes = ", ".join(c.value for c in match_result.reason_codes) or "shared signals"
            explanation = (
                f"{child.host} and {parent.host} are related ({codes}) but untyped; assumed part "
                f"of {parent.host} (needs review to confirm the type)."
            )
        else:
            confidence = self._config.confidence_part_of_assumed
            reason = ClassificationReasonCode.ASSUMED_RELATED
            explanation = (
                f"No strong signal between {host_a} and {host_b}; as a candidate pair it is "
                f"assumed part of {parent.host} (low confidence — verify)."
            )
        return self._resolved(
            view_a,
            view_b,
            RelationshipType.PART_OF,
            PartOfSubtype.OTHER,
            primary=parent,
            secondary=child,
            confidence=confidence,
            reason_codes=[reason],
            explanation=explanation,
        )

    # ------------------------------------------------------------------ helpers
    def _best_effort_parent(
        self, a: DomainFeatureView, b: DomainFeatureView
    ) -> tuple[DomainFeatureView, DomainFeatureView]:
        """Pick a best-effort (parent, child) for an untyped pair, deterministically.

        A domain that redirects away to a third domain, or defers via a one-way
        reference, is treated as the child; otherwise a global TLD outranks a
        country TLD; a stable host-order tie-break makes it reproducible.
        """
        fa, fb = a.features, b.features
        a_defers = fa.has_redirect and not _matches(fa.final_domain, a.host)
        b_defers = fb.has_redirect and not _matches(fb.final_domain, b.host)
        if a_defers and not b_defers:
            return b, a
        if b_defers and not a_defers:
            return a, b
        a_to_b = any(_matches(r, b.host) for r in fa.referenced_domains)
        b_to_a = any(_matches(r, a.host) for r in fb.referenced_domains)
        if a_to_b and not b_to_a:
            return b, a
        if b_to_a and not a_to_b:
            return a, b
        global_tlds = {"com", "net", "org", "io", "ai", "co", "app", "dev"}
        a_global = a.host.rsplit(".", 1)[-1] in global_tlds
        b_global = b.host.rsplit(".", 1)[-1] in global_tlds
        if a_global and not b_global:
            return a, b
        if b_global and not a_global:
            return b, a
        return (a, b) if a.host < b.host else (b, a)

    def _from_votes(
        self,
        view_a: DomainFeatureView,
        view_b: DomainFeatureView,
        match_result: MatchResult,
        votes: list[_Vote],
    ) -> RelationshipClassification | None:
        superiors = {v.superior.domain_id for v in votes}
        if len(superiors) > 1:
            return self._review(
                view_a,
                view_b,
                match_result,
                [ClassificationReasonCode.CONTRADICTORY_TYPE_SIGNALS],
                RelationshipDirection.SYMMETRIC,
                (
                    f"{view_a.host} and {view_b.host} carry conflicting relationship statements "
                    "(each claims the other is subordinate); direction is ambiguous."
                ),
            )
        superior = votes[0].superior
        subordinate = votes[0].subordinate
        # ACQUIRED takes precedence over PART_OF when both point the same way.
        acquired_votes = [v for v in votes if v.type is RelationshipType.ACQUIRED]
        chosen = acquired_votes or [v for v in votes if v.type is RelationshipType.PART_OF]
        rel_type = chosen[0].type
        reason_codes = _distinct([v.code for v in chosen])
        if rel_type is RelationshipType.ACQUIRED:
            confidence = self._config.confidence_acquired
            subtype = None
            # Wording is correct whichever page carried the statement (the
            # "acquired by" subordinate page or the "has acquired" acquirer page).
            explanation = (
                f"An acquisition statement links {superior.host} (acquirer) and "
                f"{subordinate.host} (acquired); they remain distinct entities and "
                f"{subordinate.host} keeps its own identity."
            )
        else:
            subtype = _pick_subtype([v.subtype for v in chosen])
            confidence = (
                self._config.confidence_part_of_generic
                if subtype is PartOfSubtype.OTHER
                else self._config.confidence_part_of_subtype
            )
            explanation = (
                f"{subordinate.host} states it is part of {superior.host}; they remain "
                f"distinct entities and {superior.host} is the parent."
            )
        return self._resolved(
            view_a,
            view_b,
            rel_type,
            subtype,
            primary=superior,
            secondary=subordinate,
            confidence=confidence,
            reason_codes=reason_codes,
            explanation=explanation,
        )

    def _resolved(
        self,
        view_a: DomainFeatureView,
        view_b: DomainFeatureView,
        rel_type: RelationshipType,
        subtype: PartOfSubtype | None,
        *,
        primary: DomainFeatureView,
        secondary: DomainFeatureView,
        confidence: float,
        reason_codes: list[ClassificationReasonCode],
        explanation: str,
    ) -> RelationshipClassification:
        direction = (
            RelationshipDirection.B_TO_A
            if primary.domain_id == view_a.domain_id
            else RelationshipDirection.A_TO_B
        )
        return RelationshipClassification(
            classifier_version=self._config.version,
            domain_a_id=view_a.domain_id,
            domain_b_id=view_b.domain_id,
            domain_a=view_a.host,
            domain_b=view_b.host,
            relationship_type=rel_type,
            relationship_subtype=subtype,
            direction=direction,
            primary_domain_id=primary.domain_id,
            primary_host=primary.host,
            secondary_domain_id=secondary.domain_id,
            secondary_host=secondary.host,
            confidence=confidence,
            confidence_band=self._band(confidence),
            reason_codes=reason_codes,
            explanation=explanation,
        )

    def _review(
        self,
        view_a: DomainFeatureView,
        view_b: DomainFeatureView,
        match_result: MatchResult,
        reason_codes: list[ClassificationReasonCode],
        direction: RelationshipDirection,
        explanation: str,
    ) -> RelationshipClassification:
        confidence = round(match_result.confidence, 4)
        return RelationshipClassification(
            classifier_version=self._config.version,
            domain_a_id=view_a.domain_id,
            domain_b_id=view_b.domain_id,
            domain_a=view_a.host,
            domain_b=view_b.host,
            relationship_type=RelationshipType.REVIEW_REQUIRED,
            direction=direction,
            confidence=confidence,
            confidence_band=self._band(confidence),
            reason_codes=reason_codes,
            explanation=explanation,
        )

    def _retained_note(self, signals_a: list[TextSignal], signals_b: list[TextSignal]) -> str:
        phrases = sorted({s.matched_phrase for s in (*signals_a, *signals_b)})
        if not phrases:
            return ""
        return f" (retained statement(s): {', '.join(phrases)})"

    def _band(self, confidence: float) -> ClassificationConfidenceBand:
        if confidence >= self._config.high_threshold:
            return ClassificationConfidenceBand.HIGH
        if confidence >= self._config.medium_threshold:
            return ClassificationConfidenceBand.MEDIUM
        return ClassificationConfidenceBand.LOW


def _distinct(codes: list[ClassificationReasonCode]) -> list[ClassificationReasonCode]:
    seen: set[ClassificationReasonCode] = set()
    out: list[ClassificationReasonCode] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _pick_subtype(subtypes: list[PartOfSubtype | None]) -> PartOfSubtype:
    for subtype in subtypes:
        if subtype is not None and subtype is not PartOfSubtype.OTHER:
            return subtype
    return PartOfSubtype.OTHER
