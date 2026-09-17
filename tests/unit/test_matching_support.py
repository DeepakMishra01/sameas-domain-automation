"""Unit tests for candidate generation, grouping, evaluation, and config."""

from typing import Any
from uuid import UUID, uuid4

from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.candidates import generate_candidate_pairs
from domain_resolver.matching.config import MATCHER_VERSION, MatcherConfig
from domain_resolver.matching.evaluation import evaluate
from domain_resolver.matching.grouping import group_domains
from domain_resolver.matching.matcher import ConfidenceBand, MatchResult
from domain_resolver.matching.reason_codes import MatchReasonCode
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.models.entities import EvidenceStrength


def _view(host: str, domain_id: UUID, **overrides: Any) -> DomainFeatureView:
    features = FeatureSet(
        feature_version="v",
        domain_id=str(domain_id),
        observation_id=str(uuid4()),
        normalized_domain=host,
        **overrides,
    )
    return DomainFeatureView(
        domain_id=domain_id, observation_id=uuid4(), host=host, features=features
    )


def _result(a: UUID, b: UUID, same: bool) -> MatchResult:
    low, high = (a, b) if a < b else (b, a)
    return MatchResult(
        domain_a_id=low,
        domain_b_id=high,
        domain_a="a",
        domain_b="b",
        same_organization=same,
        confidence=0.9 if same else 0.1,
        confidence_band=ConfidenceBand.HIGH if same else ConfidenceBand.LOW,
        matcher_version=MATCHER_VERSION,
    )


# -- candidate generation -----------------------------------------------------


def test_candidates_pair_domains_that_share_a_signal() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    views = [
        _view("aaa.test", a, email_domains=["corp.example"]),
        _view("bbb.test", b, email_domains=["corp.example"]),
        _view("zzz.test", c),  # no shared signal, dissimilar name
    ]
    pairs = {frozenset({va.domain_id, vb.domain_id}) for va, vb in generate_candidate_pairs(views)}
    assert frozenset({a, b}) in pairs
    assert frozenset({a, c}) not in pairs
    assert frozenset({b, c}) not in pairs


def test_candidates_include_structural_reference_edges() -> None:
    a, b = uuid4(), uuid4()
    views = [_view("aaa.test", a, referenced_domains=["bbb.test"]), _view("bbb.test", b)]
    pairs = {frozenset({va.domain_id, vb.domain_id}) for va, vb in generate_candidate_pairs(views)}
    assert frozenset({a, b}) in pairs


# -- grouping -----------------------------------------------------------------


def test_grouping_forms_connected_components() -> None:
    a, b, c, x, y = (uuid4() for _ in range(5))
    results = [_result(a, b, True), _result(b, c, True), _result(x, y, False)]
    groups = group_domains(results)
    by_size = {len(g.domain_ids): g for g in groups}
    assert set(by_size[3].domain_ids) == {a, b, c}  # A-B and B-C connect A,B,C
    # x and y are not grouped together (edge was not a match).
    singletons = [g for g in groups if len(g.domain_ids) == 1]
    assert {x, y}.issubset({m for g in singletons for m in g.domain_ids})


def test_grouping_records_only_direct_edges() -> None:
    a, b, c = sorted((uuid4(), uuid4(), uuid4()))
    groups = group_domains([_result(a, b, True), _result(b, c, True)])
    component = next(g for g in groups if len(g.domain_ids) == 3)
    # A-C is transitive (not a direct edge) and is not fabricated.
    assert (a, c) not in component.direct_pairs


# -- evaluation ---------------------------------------------------------------


def test_evaluation_metrics() -> None:
    a, b = uuid4(), uuid4()
    items = [
        (True, _result(a, b, True)),  # TP
        (True, _result(a, b, False)),  # FN
        (False, _result(a, b, True)),  # FP
        (False, _result(a, b, False)),  # TN
    ]
    report = evaluate(items)
    assert (report.true_positives, report.false_negatives) == (1, 1)
    assert (report.false_positives, report.true_negatives) == (1, 1)
    assert report.precision == 0.5
    assert report.recall == 0.5
    assert report.f1 == 0.5


def test_evaluation_handles_empty() -> None:
    report = evaluate([])
    assert report.precision == 0.0 and report.recall == 0.0 and report.f1 == 0.0


# -- config -------------------------------------------------------------------


def test_config_weights_and_versioning() -> None:
    config = MatcherConfig()
    assert config.positive_weight(MatchReasonCode.REDIRECT) == 0.92
    assert config.positive_weight(MatchReasonCode.DOMAIN_NAME_SIMILARITY) == 0.2
    assert config.code_tiers[MatchReasonCode.SAME_EMAIL_DOMAIN] is EvidenceStrength.STRONG
    serialized = config.to_configuration()
    assert serialized["version"] == MATCHER_VERSION
    assert MatcherConfig(version="custom").version == "custom"
