"""Unit tests for the SSRF-resistant network safety layer (no real network)."""

import socket

import httpx
import pytest

from domain_resolver.observation.errors import (
    DnsResolutionError,
    SsrfBlockedError,
    UnsafeUrlError,
)
from domain_resolver.observation.limits import DEFAULT_LIMITS
from domain_resolver.observation.network import (
    GuardedTransport,
    disallowed_ip_reason,
    parse_ip,
    resolve_and_validate,
    validate_target,
)

BLOCKED_IPS = [
    "127.0.0.1",  # loopback
    "0.0.0.0",  # unspecified
    "10.0.0.5",  # private
    "172.16.5.4",  # private
    "192.168.1.1",  # private
    "169.254.169.254",  # link-local cloud metadata
    "224.0.0.1",  # multicast
    "240.0.0.1",  # reserved
    "::1",  # ipv6 loopback
    "fe80::1",  # ipv6 link-local
    "fc00::1",  # ipv6 unique-local (private)
    "fd00:ec2::254",  # ipv6 metadata (unique-local)
    "::ffff:127.0.0.1",  # ipv4-mapped loopback
    "::ffff:10.0.0.1",  # ipv4-mapped private
]

PUBLIC_IPS = ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"]


@pytest.mark.parametrize("raw", BLOCKED_IPS)
def test_disallowed_ip_reason_blocks_unsafe(raw: str) -> None:
    import ipaddress

    assert disallowed_ip_reason(ipaddress.ip_address(raw)) is not None


@pytest.mark.parametrize("raw", PUBLIC_IPS)
def test_disallowed_ip_reason_allows_public(raw: str) -> None:
    import ipaddress

    assert disallowed_ip_reason(ipaddress.ip_address(raw)) is None


def test_parse_ip_handles_literals_and_names() -> None:
    assert parse_ip("127.0.0.1") is not None
    assert parse_ip("[::1]") is not None
    assert parse_ip("example.com") is None


@pytest.mark.parametrize("scheme", ["ftp", "file", "gopher", "ws"])
def test_validate_target_rejects_bad_scheme(scheme: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_target(httpx.URL(f"{scheme}://example.com/"), DEFAULT_LIMITS)


@pytest.mark.parametrize("port", [22, 25, 8080, 3306, 6379])
def test_validate_target_rejects_bad_port(port: int) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_target(httpx.URL(f"https://example.com:{port}/"), DEFAULT_LIMITS)


@pytest.mark.parametrize("host", ["localhost", "metadata.google.internal"])
def test_validate_target_rejects_denied_hostnames(host: str) -> None:
    with pytest.raises(SsrfBlockedError):
        validate_target(httpx.URL(f"http://{host}/"), DEFAULT_LIMITS)


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "[::1]", "10.1.2.3"])
def test_validate_target_rejects_unsafe_ip_literals(host: str) -> None:
    with pytest.raises(SsrfBlockedError):
        validate_target(httpx.URL(f"http://{host}/"), DEFAULT_LIMITS)


def test_validate_target_allows_public_https() -> None:
    validate_target(httpx.URL("https://example.com/"), DEFAULT_LIMITS)


def _fake_getaddrinfo(ip: str) -> object:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, 443, 0, 0) if ":" in ip else (ip, 443)

    def _inner(host: str, port: int, *args: object, **kwargs: object) -> list[object]:
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    return _inner


def test_resolve_and_validate_blocks_private_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.9"))
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate("evil.example", 443, DEFAULT_LIMITS)


def test_resolve_and_validate_blocks_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(SsrfBlockedError):
        resolve_and_validate("metadata.example", 443, DEFAULT_LIMITS)


def test_resolve_and_validate_allows_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    assert resolve_and_validate("good.example", 443, DEFAULT_LIMITS) == ["8.8.8.8"]


def test_resolve_and_validate_raises_on_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> list[object]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(DnsResolutionError):
        resolve_and_validate("missing.example", 443, DEFAULT_LIMITS)


def test_guarded_transport_blocks_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    # A private resolution must raise before any socket connection is attempted.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("192.168.0.10"))
    transport = GuardedTransport(DEFAULT_LIMITS)
    request = httpx.Request("GET", "https://rebind.example/")
    with pytest.raises(SsrfBlockedError):
        transport.handle_request(request)
