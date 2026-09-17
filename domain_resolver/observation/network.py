"""Network safety layer: SSRF-resistant URL validation and connection pinning.

Security decisions (defensive by default):

* Only ``http``/``https`` schemes and ports 80/443 are permitted.
* Every hostname is resolved and **all** resulting IPs are validated before any
  connection is made; a single disallowed address blocks the request.
* Loopback, private, link-local (including the ``169.254.169.254`` cloud
  metadata address), multicast, reserved, and unspecified ranges are rejected
  for both IPv4 and IPv6 (IPv4-mapped IPv6 is unwrapped and re-checked).
* ``localhost`` and known metadata hostnames are rejected by name as well.
* Connections are **pinned** to the validated IP (the socket connects to that
  exact address, with SNI/Host preserved), closing the DNS-rebinding window
  between validation and connection.
* Redirect targets are re-validated on every hop by the observer.

This module never logs response bodies or secrets.
"""

from __future__ import annotations

import ipaddress
import socket

import httpx

from domain_resolver.observation.errors import (
    DnsResolutionError,
    SsrfBlockedError,
    UnsafeUrlError,
)
from domain_resolver.observation.limits import ObservationLimits

# Hostnames that must never be contacted regardless of resolution.
_DENIED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
    }
)


def disallowed_ip_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return a reason string if ``ip`` is not a safe public destination."""
    # Unwrap IPv4-mapped/compatible IPv6 so private v4 cannot hide inside v6.
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return disallowed_ip_reason(mapped)
        sixtofour = ip.sixtofour
        if sixtofour is not None:
            return disallowed_ip_reason(sixtofour)

    if ip.is_loopback:
        return "loopback address"
    if ip.is_private:
        return "private address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_unspecified:
        return "unspecified address"
    return None


def parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Return the parsed IP if ``host`` is an IP literal, else ``None``."""
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def validate_target(url: httpx.URL, limits: ObservationLimits) -> None:
    """Validate scheme, port, and hostname of a target URL without resolving DNS.

    Raises :class:`UnsafeUrlError` for an unsupported scheme/port and
    :class:`SsrfBlockedError` for a denied hostname or an IP-literal in a
    disallowed range. DNS-based validation happens at connection time.
    """
    scheme = url.scheme.lower()
    if scheme not in limits.allowed_schemes:
        raise UnsafeUrlError(f"scheme {scheme!r} is not permitted")

    host = url.host
    if not host:
        raise UnsafeUrlError("target URL has no host")

    port = url.port if url.port is not None else (443 if scheme == "https" else 80)
    if port not in limits.allowed_ports:
        raise UnsafeUrlError(f"port {port} is not permitted")

    if host.lower() in _DENIED_HOSTNAMES:
        raise SsrfBlockedError(f"hostname {host!r} is denied")

    literal = parse_ip(host)
    if literal is not None:
        reason = disallowed_ip_reason(literal)
        if reason is not None:
            raise SsrfBlockedError(f"{host} is a {reason}")


def resolve_and_validate(host: str, port: int, limits: ObservationLimits) -> list[str]:
    """Resolve ``host`` and return validated IP strings, or raise.

    Every resolved address must be safe; if any is disallowed the whole target
    is blocked (:class:`SsrfBlockedError`). Resolution failure raises
    :class:`DnsResolutionError`.
    """
    if host.lower() in _DENIED_HOSTNAMES:
        raise SsrfBlockedError(f"hostname {host!r} is denied")

    literal = parse_ip(host)
    if literal is not None:
        reason = disallowed_ip_reason(literal)
        if reason is not None:
            raise SsrfBlockedError(f"{host} is a {reason}")
        return [literal.compressed]

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise DnsResolutionError(f"could not resolve {host!r}: {exc}") from exc

    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        raw = sockaddr[0]
        ip = ipaddress.ip_address(raw)
        reason = disallowed_ip_reason(ip)
        if reason is not None:
            raise SsrfBlockedError(f"{host} resolved to a {reason} ({raw})")
        if ip.compressed not in addresses:
            addresses.append(ip.compressed)

    if not addresses:
        raise DnsResolutionError(f"no addresses returned for {host!r}")
    return addresses


class GuardedTransport(httpx.HTTPTransport):
    """An httpx transport that validates and pins every connection.

    On each request the hostname is resolved and validated, then the request is
    rewritten to connect to a validated IP while preserving the original Host
    header and TLS SNI/verification hostname. This prevents both direct SSRF and
    DNS rebinding between validation and connection.
    """

    def __init__(self, limits: ObservationLimits, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._limits = limits

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        validate_target(request.url, self._limits)

        host = request.url.host
        scheme = request.url.scheme.lower()
        port = (
            request.url.port if request.url.port is not None else (443 if scheme == "https" else 80)
        )

        validated = resolve_and_validate(host, port, self._limits)
        pinned_ip = validated[0]

        host_header = host if port in (80, 443) else f"{host}:{port}"
        request.headers["Host"] = host_header
        request.extensions = {**request.extensions, "sni_hostname": host}
        request.url = request.url.copy_with(host=pinned_ip)
        return super().handle_request(request)
