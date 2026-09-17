"""Unit tests for deterministic Phase 4 normalization (no network/DB)."""

import pytest

from domain_resolver.features import normalization as norm


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("WWW.Example.com.", "example.com"),
        ("https://WWW.Example.COM:443/x", "example.com"),
        ("bücher.example", "xn--bcher-kva.example"),
    ],
)
def test_normalize_domain_value(raw: str, expected: str) -> None:
    assert norm.normalize_domain_value(raw) == expected


def test_host_from_url() -> None:
    assert norm.host_from_url("https://www.Example.com/path?q=1") == "example.com"
    assert norm.host_from_url("sub.example.com/x") == "sub.example.com"
    with pytest.raises(ValueError):
        norm.host_from_url("not a url")


def test_normalize_url() -> None:
    assert (
        norm.normalize_url("HTTPS://Example.COM:443/Path/?q=1#frag")
        == "https://example.com/Path/?q=1"
    )
    assert norm.normalize_url("http://example.com") == "http://example.com/"
    assert norm.normalize_url("http://example.com:8080/x") == "http://example.com:8080/x"
    with pytest.raises(ValueError):
        norm.normalize_url("ftp://example.com/")
    with pytest.raises(ValueError):
        norm.normalize_url("https:///nohost")


def test_normalize_text_unicode_and_whitespace() -> None:
    assert norm.normalize_text("  Café\t\nRÉSUMÉ  ") == "café résumé"
    # NFKC folds compatibility characters (e.g. fullwidth) deterministically.
    assert norm.normalize_text("ＡＢＣ") == "abc"


def test_tokenize_is_bounded_and_deterministic() -> None:
    assert norm.tokenize("Hello,  World! 123") == ["hello", "world", "123"]
    big = " ".join(f"w{i}" for i in range(1000))
    assert len(norm.tokenize(big, max_tokens=50)) == 50


def test_text_fingerprint_is_stable() -> None:
    a = norm.text_fingerprint("Same TEXT here")
    b = norm.text_fingerprint("same   text here")
    assert a == b  # normalization makes these identical
    assert a != norm.text_fingerprint("different")


def test_normalize_email() -> None:
    local, domain = norm.normalize_email("John.Doe@Example.COM")
    assert local == "John.Doe"
    assert domain == "example.com"
    with pytest.raises(ValueError):
        norm.normalize_email("not-an-email")
    with pytest.raises(ValueError):
        norm.normalize_email("user@localhost")


def test_scan_emails() -> None:
    found = norm.scan_emails("reach Info@Acme.io or sales@acme.io, not bad@")
    assert found == ["Info@Acme.io", "sales@acme.io"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+1 (415) 555-2671", "+14155552671"),
        ("0044 20 7946 0958", "00442079460958"),
        ("+91-98765-43210", "+919876543210"),
    ],
)
def test_normalize_phone(raw: str, expected: str) -> None:
    assert norm.normalize_phone(raw) == expected


def test_normalize_phone_rejects_short() -> None:
    with pytest.raises(ValueError):
        norm.normalize_phone("12345")


@pytest.mark.parametrize(
    ("url", "platform", "normalized"),
    [
        ("https://www.linkedin.com/company/acme/", "linkedin", "https://linkedin.com/company/acme"),
        ("http://twitter.com/acme", "twitter", "https://twitter.com/acme"),
        ("https://x.com/acme", "twitter", "https://x.com/acme"),
    ],
)
def test_normalize_social_url(url: str, platform: str, normalized: str) -> None:
    result = norm.normalize_social_url(url)
    assert result == (platform, normalized)


def test_normalize_social_url_unknown_platform() -> None:
    assert norm.normalize_social_url("https://example.com/profile") is None


def test_is_same_site() -> None:
    assert norm.is_same_site("blog.example.com", "example.com") is True
    assert norm.is_same_site("example.com", "example.com") is True
    assert norm.is_same_site("example.com", "other.com") is False
    assert norm.is_same_site("", "example.com") is False
