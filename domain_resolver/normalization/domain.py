"""Domain input normalization without performing network access."""

from urllib.parse import urlsplit


def normalize_domain(value: str) -> str:
    """Return a lowercase IDNA hostname without scheme, `www.`, port, or path.

    The function accepts either a bare host or an HTTP(S) URL. It rejects empty
    inputs, non-web schemes, credentials, query/fragment-only inputs, and hosts
    that cannot be represented as an IDNA hostname.
    """
    candidate = value.strip()
    if not candidate:
        raise ValueError("domain must not be empty")

    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}", scheme="")
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        raise ValueError("domain must use HTTP(S) when a scheme is supplied")
    if parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("domain must contain a hostname without credentials")

    try:
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("domain is not a valid IDNA hostname") from exc
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not hostname or "." not in hostname:
        raise ValueError("domain must be a fully qualified hostname")
    return hostname
