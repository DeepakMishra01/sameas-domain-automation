"""Unit tests for the DNS observer using a mocked resolver (no real DNS)."""

from typing import Any

import dns.exception
import dns.resolver
import pytest

from domain_resolver.models.entities import ObservationErrorCategory
from domain_resolver.observation.dns_observer import DnsObserver


class _FakeRdata:
    def __init__(self, text: str) -> None:
        self._text = text

    def to_text(self) -> str:
        return self._text


def _install(monkeypatch: pytest.MonkeyPatch, behaviour: dict[str, Any]) -> None:
    def fake_resolve(self: Any, qname: str, rdtype: str, **kwargs: Any) -> list[_FakeRdata]:
        outcome = behaviour[rdtype]
        if isinstance(outcome, Exception):
            raise outcome
        return [_FakeRdata(v) for v in outcome]

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", fake_resolve)


def test_dns_success_records_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "A": ["93.184.216.34"],
            "AAAA": ["2606:2800:220:1:248:1893:25c8:1946"],
            "CNAME": dns.resolver.NoAnswer(),
            "MX": ["10 mail.example.com."],
            "NS": ["ns1.example.com.", "ns2.example.com."],
        },
    )
    result = DnsObserver().observe("example.com")
    by_type = {r.record_type: r for r in result.records}
    assert by_type["A"].values == ["93.184.216.34"]
    assert by_type["NS"].values == ["ns1.example.com.", "ns2.example.com."]
    assert by_type["CNAME"].values == []
    assert result.error_category is None


def test_dns_nxdomain(monkeypatch: pytest.MonkeyPatch) -> None:
    nx = dns.resolver.NXDOMAIN()
    _install(monkeypatch, {rt: nx for rt in ("A", "AAAA", "CNAME", "MX", "NS")})
    result = DnsObserver().observe("does-not-exist.example")
    assert result.error_category is ObservationErrorCategory.DNS_ERROR
    assert result.error_detail == "NXDOMAIN"
    assert all(r.error == "NXDOMAIN" for r in result.records)


def test_dns_timeout_is_recorded_per_type(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch, {rt: dns.exception.Timeout() for rt in ("A", "AAAA", "CNAME", "MX", "NS")}
    )
    result = DnsObserver().observe("slow.example")
    assert all(r.error == "TIMEOUT" for r in result.records)
    # A timeout is not an NXDOMAIN, so no observation-level DNS_ERROR is asserted.
    assert result.error_category is None


def test_dns_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Any, qname: str, rdtype: str, **kwargs: Any) -> list[_FakeRdata]:
        raise dns.exception.DNSException("unexpected")

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", boom)
    result = DnsObserver().observe("weird.example")
    assert all(r.error == "DNSException" for r in result.records)
