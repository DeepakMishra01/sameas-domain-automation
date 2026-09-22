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

        # --- 2 & 3. ACQUIRED / PART_OF from explicit text statements ----------
        votes = [_Vote(view_a, view_b, s) for s in signals_a] + [
            _Vote(view_b, view_a, s) for s in signals_b
        ]
        if votes:
            typed = self._from_votes(view_a, view_b, match_result, votes)
            if typed is not None:
                return typed

        # --- Canonical: SAME_AS only if corroborated, else REVIEW -------------
        can_ab = _matches(view_a.features.canonical_domain, host_b)
        can_ba = _matches(view_b.features.canonical_domain, host_a)
        if can_ab or can_ba:
            source, target = (view_a, view_b) if can_ab else (view_b, view_a)
            corroborated = not self._config.require_canonical_corroboration or _identical_content(
                view_a.features, view_b.features
            )
            if corroborated:
                return self._resolved(
                    view_a,
                    view_b,
                    RelationshipType.SAME_AS,
                    None,
                    primary=target,
                    secondary=source,
                    confidence=self._config.confidence_canonical_same_as,
                    reason_codes=[ClassificationReasonCode.CANONICAL_TO_PRIMARY_CORROBORATED],
                    explanation=(
                        f"{source.host} declares {target.host} canonical and their content is "
                        f"identical, so they are the same entity; {target.host} is primary."
                    ),
                )
            return self._review(
                view_a,
                view_b,
                match_result,
                [ClassificationReasonCode.CANONICAL_WITHOUT_CORROBORATION],
                RelationshipDirection.A_TO_B if can_ab else RelationshipDirection.B_TO_A,
                (
                    f"{source.host} declares {target.host} canonical, but their content differs; "
                    "a redirect or corroborating evidence is needed to confirm SAME_AS."
                ),
            )

        # --- 4. Related but untyped -> REVIEW (never collapse identities) -----
        if match_result.same_organization:
            return self._review(
                view_a,
                view_b,
                match_result,
                [ClassificationReasonCode.RELATED_TYPE_UNDETERMINED],
                RelationshipDirection.UNDETERMINED,
                (
                    f"{host_a} and {host_b} share signals "
                    f"({', '.join(c.value for c in match_result.reason_codes) or 'related'}) "
                    "but there is no redirect or explicit statement to type the relationship."
                ),
            )

        # --- 5. UNRELATED -----------------------------------------------------
        confidence = round(1.0 - match_result.confidence, 4)
        return RelationshipClassification(
            classifier_version=self._config.version,
            domain_a_id=view_a.domain_id,
            domain_b_id=view_b.domain_id,
            domain_a=host_a,
            domain_b=host_b,
            relationship_type=RelationshipType.UNRELATED,
            direction=RelationshipDirection.UNDETERMINED,
            confidence=confidence,
            confidence_band=self._band(confidence),
            reason_codes=[ClassificationReasonCode.NO_CREDIBLE_RELATIONSHIP],
            explanation=f"No credible relationship observed between {host_a} and {host_b}.",
        )

    # ------------------------------------------------------------------ helpers
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
