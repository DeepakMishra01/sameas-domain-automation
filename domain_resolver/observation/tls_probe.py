"""Best-effort, SSRF-safe TLS certificate probe.

Captures the leaf certificate's Subject Alternative Names, SHA-256 fingerprint,
and subject common name for an HTTPS host. Used only as *supporting* identity
evidence — a shared certificate never establishes SAME_AS on its own.

Safety: the host is resolved and validated through the same SSRF guard as the
HTTP observer, and the socket is pinned to the validated IP with SNI preserved,
closing the DNS-rebinding window. Any failure returns ``None`` — the probe never
raises and never blocks an observation.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
from dataclasses import dataclass, field
from typing import Any

from domain_resolver.observation.limits import ObservationLimits
from domain_resolver.observation.network import resolve_and_validate


@dataclass(frozen=True)
class TlsCertificateFacts:
    sans: list[str] = field(default_factory=list)
    fingerprint_sha256: str | None = None
    subject_cn: str | None = None


def probe_tls_certificate(host: str, limits: ObservationLimits) -> TlsCertificateFacts | None:
    """Return leaf-certificate facts for ``host`` over TLS, or ``None`` on any issue."""
    try:
        addresses = resolve_and_validate(host, 443, limits)
    except Exception:  # noqa: BLE001 - any resolution/SSRF issue -> skip the probe
        return None
    pinned_ip = addresses[0]

    context = ssl.create_default_context()
    try:
        with socket.create_connection((pinned_ip, 443), timeout=limits.connect_timeout) as raw:
            raw.settimeout(limits.read_timeout)
            with context.wrap_socket(raw, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
                info = tls.getpeercert()
    except Exception:  # noqa: BLE001 - handshake/timeout/verification failure -> skip
        return None

    if der is None:
        return None
    fingerprint = hashlib.sha256(der).hexdigest()
    sans: list[str] = []
    subject_cn: str | None = None
    info_any: Any = info or {}
    for entry in info_any.get("subjectAltName", ()):
        if isinstance(entry, tuple) and len(entry) == 2 and str(entry[0]).lower() == "dns":
            value = str(entry[1]).lower().rstrip(".")
            if value and value not in sans:
                sans.append(value)
    for rdn in info_any.get("subject", ()):
        for pair in rdn:
            if isinstance(pair, tuple) and len(pair) == 2 and pair[0] == "commonName" and pair[1]:
                subject_cn = str(pair[1]).lower().rstrip(".")
    return TlsCertificateFacts(
        sans=sorted(sans), fingerprint_sha256=fingerprint, subject_cn=subject_cn
    )
