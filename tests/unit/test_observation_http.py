"""Unit tests for the HTTP observer using an in-memory mock transport.

No real websites are contacted. Redirect handling, bounding, timing, and error
classification are all exercised against a deterministic mock.
"""

import ssl
from collections.abc import Callable
from dataclasses import replace

import httpx

from domain_resolver.models.entities import ObservationErrorCategory
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.limits import DEFAULT_LIMITS, ObservationLimits

Handler = Callable[[httpx.Request], httpx.Response]


def _observer(handler: Handler, limits: ObservationLimits = DEFAULT_LIMITS) -> HttpObserver:
    return HttpObserver(limits=limits, transport=httpx.MockTransport(handler))


def test_simple_html_200() -> None:
    html = (
        b"<html><head><title>Acme</title>"
        b'<link rel="canonical" href="https://acme.test/"></head></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=html
        )

    obs = _observer(handler).observe("acme.test")
    assert obs.status_code == 200
    assert obs.content_type is not None and obs.content_type.startswith("text/html")
    assert obs.response_size_bytes == len(html)
    assert obs.html is not None
    assert obs.html.title == "Acme"
    assert obs.html.canonical_url == "https://acme.test/"
    assert obs.html.content_hash is not None
    assert obs.error_category is None
    assert obs.elapsed_ms is not None


def test_redirect_chain_is_recorded_not_interpreted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "zeptonow.test":
            return httpx.Response(301, headers={"location": "https://www.zeptonow.test/"})
        if host == "www.zeptonow.test":
            return httpx.Response(301, headers={"location": "https://zepto.test/"})
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<title>Z</title>"
        )

    obs = _observer(handler).observe("zeptonow.test")
    assert obs.status_code == 200
    assert [hop.status_code for hop in obs.redirect_chain] == [301, 301]
    assert obs.redirect_chain[0].target_url == "https://www.zeptonow.test/"
    assert obs.final_url == "https://zepto.test/"
    assert obs.final_hostname == "zepto.test"
    # No same-as conclusion is present anywhere in the factual record.
    assert obs.error_category is None


def test_redirect_loop_detected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        target = "https://b.test/" if host == "a.test" else "https://a.test/"
        return httpx.Response(302, headers={"location": target})

    obs = _observer(handler).observe("a.test")
    assert obs.error_category is ObservationErrorCategory.REDIRECT_LIMIT
    assert obs.error_detail == "redirect loop detected"


def test_redirect_limit_exceeded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or "0")
        return httpx.Response(301, headers={"location": f"https://chain.test/{n + 1}"})

    limits = replace(DEFAULT_LIMITS, max_redirects=2)
    obs = HttpObserver(limits=limits, transport=httpx.MockTransport(handler)).observe("chain.test")
    assert obs.error_category is ObservationErrorCategory.REDIRECT_LIMIT
    assert obs.error_detail == "maximum redirects exceeded"
    assert len(obs.redirect_chain) == 2


def test_response_too_large() -> None:
    big = b"<html>" + b"A" * 5000 + b"</html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=big)

    limits = replace(DEFAULT_LIMITS, max_body_bytes=1000)
    obs = HttpObserver(limits=limits, transport=httpx.MockTransport(handler)).observe("big.test")
    assert obs.error_category is ObservationErrorCategory.RESPONSE_TOO_LARGE


def test_timeout_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    obs = _observer(handler).observe("slow.test")
    assert obs.error_category is ObservationErrorCategory.TIMEOUT
    assert obs.status_code is None


def test_connection_error_falls_back_to_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "https":
            raise httpx.ConnectError("no tls", request=request)
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<title>x</title>"
        )

    obs = _observer(handler).observe("fallback.test")
    assert obs.scheme_attempts == ["https", "http"]
    assert obs.status_code == 200


def test_ssl_error_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bad cert", request=request) from ssl.SSLError("handshake")

    obs = _observer(handler).observe("badssl.test")
    assert obs.error_category is ObservationErrorCategory.SSL_ERROR


def test_status_classification_is_factual() -> None:
    cases = {
        "403.test": (403, ObservationErrorCategory.HTTP_403),
        "429.test": (429, ObservationErrorCategory.HTTP_429),
        "404.test": (404, ObservationErrorCategory.HTTP_4XX),
        "500.test": (500, ObservationErrorCategory.HTTP_5XX),
    }
    for host, (status, expected) in cases.items():

        def handler(request: httpx.Request, _status: int = status) -> httpx.Response:
            return httpx.Response(_status, headers={"content-type": "text/plain"}, content=b"x")

        obs = _observer(handler).observe(host)
        assert obs.status_code == status
        assert obs.error_category is expected


def test_content_hash_is_deterministic() -> None:
    def make(content: bytes) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=content)

        return handler

    body = b"<html><title>Same</title></html>"
    first = _observer(make(body)).observe("h1.test")
    second = _observer(make(body)).observe("h2.test")
    different = _observer(make(b"<html><title>Other</title></html>")).observe("h3.test")
    assert first.html is not None and second.html is not None and different.html is not None
    assert first.html.content_hash == second.html.content_hash
    assert first.html.content_hash != different.html.content_hash


def test_meta_refresh_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.test":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b'<meta http-equiv="refresh" content="0;url=https://dest.test/">',
            )
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<title>Dest</title>"
        )

    obs = _observer(handler).observe("start.test")
    assert obs.final_hostname == "dest.test"
    assert any(hop.kind == "meta_refresh" for hop in obs.redirect_chain)
    assert obs.html is not None and obs.html.title == "Dest"
    assert obs.error_category is None


def test_meta_refresh_into_private_address_is_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b'<meta http-equiv="refresh" content="0;url=http://127.0.0.1/">',
        )

    obs = _observer(handler).observe("start.test")
    assert obs.final_hostname == "start.test"  # unsafe meta target not followed
    assert obs.redirect_chain == []
    assert obs.html is not None and obs.html.meta_refresh_url == "http://127.0.0.1/"


def test_redirect_into_private_address_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "evil.test":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/"})
        return httpx.Response(200, content=b"unreachable")

    obs = _observer(handler).observe("evil.test")
    assert obs.error_category is ObservationErrorCategory.SSRF_BLOCKED
