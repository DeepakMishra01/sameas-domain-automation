"""Deterministic, side-effect-free normalization for Phase 4.

Every function is pure and reproducible (no network, no DNS, no clock). Callers
keep the original raw value; these functions only produce comparison-ready
normalized forms. Invalid input raises :class:`ValueError` so the extractor can
record a structured warning instead of guessing.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from domain_resolver.normalization import normalize_domain

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[0-9a-z]+")
_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.IGNORECASE)
_EMAIL_SCAN_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE)
_DEFAULT_PORTS = {"http": 80, "https": 443}

# host suffix -> canonical platform name
_SOCIAL_PLATFORMS: dict[str, str] = {
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "github.com": "github",
    "t.me": "telegram",
    "medium.com": "medium",
    "pinterest.com": "pinterest",
    "tiktok.com": "tiktok",
}


def normalize_domain_value(value: str) -> str:
    """Normalize a bare domain/host to a lowercase registrable hostname.

    Delegates to the shared, network-free domain normalizer (lowercase, IDNA,
    scheme/port/``www.`` stripped, trailing dot removed).
    """
    return normalize_domain(value)


def host_from_url(url: str) -> str:
    """Extract and normalize the hostname from an absolute URL.

    Raises ``ValueError`` if the URL has no usable host.
    """
    parts = urlsplit(url if "://" in url else f"//{url}", scheme="")
    if not parts.hostname:
        raise ValueError("url has no host")
    return normalize_domain(parts.hostname)


def normalize_url(url: str) -> str:
    """Normalize an http(s) URL: lowercase scheme/host, drop default port and
    fragment, collapse an empty path to ``/``. Preserves path and query.

    Raises ``ValueError`` for a non-http(s) or hostless URL.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise ValueError(f"unsupported scheme {scheme!r}")
    if not parts.hostname:
        raise ValueError("url has no host")
    host = parts.hostname.lower().rstrip(".")
    netloc = host
    if parts.port is not None and parts.port != _DEFAULT_PORTS[scheme]:
        netloc = f"{host}:{parts.port}"
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def normalize_text(value: str) -> str:
    """Unicode-normalize (NFKC), lowercase, and collapse whitespace."""
    normalized = unicodedata.normalize("NFKC", value)
    return _WS_RE.sub(" ", normalized).strip().lower()


def tokenize(value: str, *, max_tokens: int = 512) -> list[str]:
    """Deterministically tokenize text into bounded lowercase alphanumeric tokens."""
    tokens = _TOKEN_RE.findall(normalize_text(value))
    return tokens[:max_tokens]


def text_fingerprint(value: str) -> str:
    """Stable SHA-256 fingerprint of the normalized text (deterministic)."""
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def normalize_email(value: str) -> tuple[str, str]:
    """Return ``(local_part, normalized_domain)`` for a valid email address.

    The local part is preserved as-is (its semantics are case-sensitive in
    general); only the domain is lowercased/normalized. Raises ``ValueError`` on
    an invalid address.
    """
    candidate = value.strip()
    if not _EMAIL_RE.match(candidate):
        raise ValueError(f"invalid email address {value!r}")
    local, _, domain = candidate.rpartition("@")
    return local, normalize_domain(domain)


def scan_emails(text: str) -> list[str]:
    """Find syntactically valid email addresses in text (local part lowercased
    only for de-duplication is avoided; addresses returned as matched)."""
    return _EMAIL_SCAN_RE.findall(text)


def normalize_phone(value: str) -> str:
    """Strip formatting noise to an optional leading ``+`` and digits.

    Preserves a country code when present; never invents one. Raises
    ``ValueError`` if fewer than 7 digits remain (not a usable phone number).
    """
    stripped = value.strip()
    has_plus = stripped.startswith("+")
    digits = re.sub(r"\D", "", stripped)
    if len(digits) < 7:
        raise ValueError(f"not enough digits for a phone number: {value!r}")
    return f"+{digits}" if has_plus else digits


def normalize_social_url(url: str) -> tuple[str, str] | None:
    """Return ``(platform, normalized_url)`` for a known social platform, else None.

    Normalizes to https, lowercases the host (drops ``www.``), keeps the path,
    and drops query/fragment. Never claims two profiles are the same entity.
    """
    try:
        parts = urlsplit(url if "://" in url else f"https://{url}")
    except ValueError:
        return None
    host = (parts.hostname or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    platform = _platform_for_host(host)
    if platform is None:
        return None
    path = parts.path.rstrip("/") or "/"
    return platform, urlunsplit(("https", host, path, "", ""))


def is_same_site(host_a: str, host_b: str) -> bool:
    """True if the two hosts are equal or one is a subdomain of the other.

    Deterministic and stdlib-only; used to decide whether a link is a
    cross-domain reference without depending on a public-suffix list.
    """
    a = host_a.lower().rstrip(".")
    b = host_b.lower().rstrip(".")
    if not a or not b:
        return False
    return a == b or a.endswith(f".{b}") or b.endswith(f".{a}")


def _platform_for_host(host: str) -> str | None:
    for suffix, platform in _SOCIAL_PLATFORMS.items():
        if host == suffix or host.endswith(f".{suffix}"):
            return platform
    return None
