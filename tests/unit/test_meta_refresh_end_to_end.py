"""End-to-end (observe -> extract -> match) test for meta-refresh redirects.

Reproduces the real ariseall.com -> khareclasses.com case deterministically with
an in-memory transport (no network): a "Redirecting..." page whose only link to
the destination is a ``<meta http-equiv="refresh">`` must now yield a REDIRECT
match, since the observer follows meta-refresh (no JavaScript executed).
"""

from datetime import UTC, datetime
from uuid import uuid4

import httpx

from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.matching.reason_codes import MatchReasonCode
from domain_resolver.matching.views import DomainFeatureView
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.results import DnsObservation, ObservationResult


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "ariseall.test":
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<title>Redirecting...</title>"
            b'<meta http-equiv="refresh" content="5;url=https://khareclasses.test/">',
        )
    return httpx.Response(
        200, headers={"content-type": "text/html"}, content=b"<title>Khare</title>"
    )


def _view(host: str) -> DomainFeatureView:
    http = HttpObserver(transport=httpx.MockTransport(_handler)).observe(host)
    result = ObservationResult(
        collector_version="c",
        observed_at=datetime.now(UTC),
        dns=DnsObservation(hostname=host),
        http=http,
    )
    domain_id, observation_id = uuid4(), uuid4()
    output = FeatureExtractor("feature-extractor-test").extract(
        domain_id=domain_id, observation_id=observation_id, domain_host=host, result=result
    )
    return DomainFeatureView(
        domain_id=domain_id, observation_id=observation_id, host=host, features=output.features
    )


def test_meta_refresh_produces_same_org_match() -> None:
    result = OrganizationMatcher().match(_view("ariseall.test"), _view("khareclasses.test"))
    assert result.same_organization is True
    assert MatchReasonCode.REDIRECT in result.reason_codes
