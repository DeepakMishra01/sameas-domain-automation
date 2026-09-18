"""Unit tests for the deterministic primary-domain resolver (no DB/network)."""

from uuid import UUID, uuid4

from domain_resolver.features.results import FeatureSet
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.resolution.config import ResolverConfig
from domain_resolver.resolution.reason_codes import PrimaryReasonCode
from domain_resolver.resolution.resolver import PrimaryDomainResolver
from domain_resolver.resolution.results import PrimaryDesignation, ResolutionStatus

RESOLVER = PrimaryDomainResolver()


def _view(
    host: str,
    domain_id: UUID | None = None,
    *,
    redirect_to: str | None = None,
    canonical: str | None = None,
    references: list[str] | None = None,
    title: str | None = None,
    text: str | None = None,
) -> DomainFeatureView:
    domain_id = domain_id or uuid4()
    features = FeatureSet(
        feature_version="v",
        domain_id=str(domain_id),
        observation_id=str(uuid4()),
        normalized_domain=host,
        has_redirect=redirect_to is not None,
        redirect_target_domain=redirect_to,
        final_domain=redirect_to or host,
        has_canonical=canonical is not None,
        canonical_domain=canonical,
        referenced_domains=references or [],
        normalized_title=title,
        normalized_text_excerpt=text,
    )
    return DomainFeatureView(
        domain_id=domain_id, observation_id=uuid4(), host=host, features=features
    )


def _primary_host(resolution: object) -> str | None:
    return resolution.primary_host  # type: ignore[attr-defined]


def test_redirect_target_is_primary() -> None:
    a = _view("secondary.test", redirect_to="primary.test")
    b = _view("primary.test", title="Primary", text="welcome")
    res = RESOLVER.resolve([a, b])
    assert res.status is ResolutionStatus.RESOLVED
    assert res.primary_host == "primary.test"
    designations = {s.host: s.designation for s in res.scores}
    assert designations["primary.test"] is PrimaryDesignation.PRIMARY
    assert designations["secondary.test"] is PrimaryDesignation.SECONDARY
    primary = next(s for s in res.scores if s.designation is PrimaryDesignation.PRIMARY)
    assert PrimaryReasonCode.REDIRECT_TARGET in primary.reason_codes


def test_canonical_target_is_primary() -> None:
    a = _view("a.test", canonical="b.test")
    b = _view("b.test", title="B")
    res = RESOLVER.resolve([a, b])
    assert res.status is ResolutionStatus.RESOLVED
    assert res.primary_host == "b.test"


def test_multiple_domains_redirect_to_one() -> None:
    a = _view("a.test", redirect_to="hub.test")
    b = _view("b.test", redirect_to="hub.test")
    hub = _view("hub.test", title="Hub", text="content")
    res = RESOLVER.resolve([a, b, hub])
    assert res.status is ResolutionStatus.RESOLVED
    assert res.primary_host == "hub.test"
    secondaries = {s.host for s in res.scores if s.designation is PrimaryDesignation.SECONDARY}
    assert secondaries == {"a.test", "b.test"}


def test_redirect_chain_terminal_is_primary() -> None:
    # c -> a -> b : b is the terminal destination and should be primary.
    a = _view("a.test", redirect_to="b.test")
    b = _view("b.test", title="B", text="hi")
    c = _view("c.test", redirect_to="a.test")
    res = RESOLVER.resolve([a, b, c])
    assert res.status is ResolutionStatus.RESOLVED
    assert res.primary_host == "b.test"


def test_one_way_reference_alone_is_not_enough() -> None:
    a = _view("a.test", references=["b.test"], title="A", text="a")
    b = _view("b.test", title="B", text="b")
    res = RESOLVER.resolve([a, b])
    # A weak reference plus both being active does not clearly identify a primary.
    assert res.status is ResolutionStatus.REVIEW_REQUIRED
    assert all(s.designation is PrimaryDesignation.UNRESOLVED for s in res.scores)


def test_no_evidence_is_unresolved() -> None:
    res = RESOLVER.resolve([_view("a.test"), _view("b.test")])
    assert res.status is ResolutionStatus.REVIEW_REQUIRED
    assert res.primary_domain_id is None


def test_two_active_sites_without_direction_are_ambiguous() -> None:
    a = _view("a.test", title="A", text="a")
    b = _view("b.test", title="B", text="b")
    res = RESOLVER.resolve([a, b])
    assert res.status is ResolutionStatus.REVIEW_REQUIRED  # equal scores, no direction


def test_mutual_redirect_is_a_conflict() -> None:
    a = _view("a.test", redirect_to="b.test")
    b = _view("b.test", redirect_to="a.test")
    res = RESOLVER.resolve([a, b])
    assert res.status is ResolutionStatus.REVIEW_REQUIRED
    assert res.conflicts and res.conflicts[0]["type"] == "MUTUAL_DIRECTION"


def test_mutual_canonical_is_a_conflict() -> None:
    a = _view("a.test", canonical="b.test")
    b = _view("b.test", canonical="a.test")
    res = RESOLVER.resolve([a, b])
    assert res.status is ResolutionStatus.REVIEW_REQUIRED
    assert res.conflicts


def test_resolution_is_deterministic() -> None:
    ids = (UUID(int=1), UUID(int=2))
    build = lambda: [  # noqa: E731 - concise fixture
        _view("secondary.test", ids[0], redirect_to="primary.test"),
        _view("primary.test", ids[1], title="P", text="x"),
    ]
    first = RESOLVER.resolve(build())
    second = RESOLVER.resolve(build())
    assert first.primary_domain_id == second.primary_domain_id
    assert [s.primary_score for s in first.scores] == [s.primary_score for s in second.scores]


def test_resolver_version_is_recorded() -> None:
    resolver = PrimaryDomainResolver(ResolverConfig(version="primary-test-v9"))
    res = resolver.resolve([_view("a.test", redirect_to="b.test"), _view("b.test", title="B")])
    assert res.resolver_version == "primary-test-v9"
