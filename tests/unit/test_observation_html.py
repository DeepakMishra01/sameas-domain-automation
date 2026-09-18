"""Unit tests for bounded HTML fact extraction."""

from dataclasses import replace

from domain_resolver.observation.html_extract import extract_html_summary
from domain_resolver.observation.limits import DEFAULT_LIMITS

SAMPLE = """
<html><head>
<title>  Zepto  Groceries </title>
<meta name="description" content="Fast grocery delivery">
<link rel="canonical" href="https://zepto.com/"/>
<style>.x{color:red}</style>
</head>
<body>
<script>var secret = 1;</script>
<p>Welcome to Zepto</p>
<a href="https://zepto.com/about">About</a>
<a href="https://zepto.com/about">About dup</a>
<a href="/careers">Careers</a>
</body></html>
"""


def test_extract_core_fields() -> None:
    summary = extract_html_summary(SAMPLE, content_hash="abc123", limits=DEFAULT_LIMITS)
    assert summary.title == "Zepto Groceries"
    assert summary.meta_description == "Fast grocery delivery"
    assert summary.canonical_url == "https://zepto.com/"
    assert summary.content_hash == "abc123"


def test_links_are_deduped_and_bounded() -> None:
    summary = extract_html_summary(SAMPLE, content_hash=None, limits=DEFAULT_LIMITS)
    assert summary.links == ["https://zepto.com/about", "/careers"]


def test_script_and_style_excluded_from_text() -> None:
    summary = extract_html_summary(SAMPLE, content_hash=None, limits=DEFAULT_LIMITS)
    assert summary.text_excerpt is not None
    assert "secret" not in summary.text_excerpt
    assert "color:red" not in summary.text_excerpt
    assert "Welcome to Zepto" in summary.text_excerpt


def test_text_excerpt_is_truncated_to_limit() -> None:
    tight = replace(DEFAULT_LIMITS, max_text_chars=10)
    body = "<html><body><p>" + ("A" * 500) + "</p></body></html>"
    summary = extract_html_summary(body, content_hash=None, limits=tight)
    assert summary.text_excerpt is not None
    assert len(summary.text_excerpt) <= 10
    assert summary.truncated is True


def test_og_description_fallback() -> None:
    body = '<html><head><meta property="og:description" content="OG text"></head></html>'
    summary = extract_html_summary(body, content_hash=None, limits=DEFAULT_LIMITS)
    assert summary.meta_description == "OG text"


def test_meta_refresh_target_extracted() -> None:
    body = '<html><head><meta http-equiv="refresh" content="5;url=https://khareclasses.com"></head></html>'
    summary = extract_html_summary(body, None, DEFAULT_LIMITS)
    assert summary.meta_refresh_url == "https://khareclasses.com"


def test_meta_refresh_quoted_and_uppercase() -> None:
    body = '<html><head><meta http-equiv="REFRESH" content="0; URL=\'https://x.example/p\'"></head></html>'
    summary = extract_html_summary(body, None, DEFAULT_LIMITS)
    assert summary.meta_refresh_url == "https://x.example/p"


def test_meta_refresh_self_reload_is_ignored() -> None:
    body = '<html><head><meta http-equiv="refresh" content="30"></head></html>'
    summary = extract_html_summary(body, None, DEFAULT_LIMITS)
    assert summary.meta_refresh_url is None


def test_missing_fields_are_none() -> None:
    summary = extract_html_summary("<html><body>hi</body></html>", None, DEFAULT_LIMITS)
    assert summary.title is None
    assert summary.canonical_url is None
    assert summary.meta_description is None
