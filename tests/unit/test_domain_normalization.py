import pytest

from domain_resolver.normalization import normalize_domain


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://WWW.Example.COM:443/path?q=1", "example.com"),
        ("example.com/landing", "example.com"),
        ("https://bücher.example/", "xn--bcher-kva.example"),
    ],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", ["", "ftp://example.com", "http://user@example.com", "localhost"])
def test_normalize_domain_rejects_invalid_input(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(raw)
