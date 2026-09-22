"""Unit tests for Stage 2 identity fact extraction from HTML."""

from domain_resolver.observation.html_extract import extract_html_summary

_PAGE = """
<html><head>
<title>Acme Store</title>
<meta property="og:site_name" content="Acme">
<meta property="og:title" content="Acme Store - Home">
<link rel="icon" href="/static/favicon-32.png">
<link rel="canonical" href="https://acme.example/">
<script type="application/ld+json">
{"@type": "Organization", "name": "Acme Inc", "legalName": "Acme Incorporated"}
</script>
<script>
  gtag('config', 'G-ABC123DEF4');
  var gtm = 'GTM-ABCD12';
  ga('create', 'UA-111222-3', 'auto');
</script>
</head><body>
<p>Welcome to Acme.</p>
<footer>© 2024 Acme Inc. All rights reserved.</footer>
</body></html>
"""


def test_extracts_opengraph_site_and_title() -> None:
    s = extract_html_summary(_PAGE, "hash")
    assert s.og_site_name == "Acme"
    assert s.og_title == "Acme Store - Home"


def test_extracts_favicon_href() -> None:
    assert extract_html_summary(_PAGE, "hash").favicon_href == "/static/favicon-32.png"


def test_extracts_jsonld_org_names() -> None:
    names = extract_html_summary(_PAGE, "hash").jsonld_names
    assert "Acme Inc" in names
    assert "Acme Incorporated" in names


def test_extracts_analytics_ids() -> None:
    ids = set(extract_html_summary(_PAGE, "hash").analytics_ids)
    assert {"G-ABC123DEF4", "GTM-ABCD12", "UA-111222-3"} <= ids


def test_extracts_copyright_owner() -> None:
    owner = extract_html_summary(_PAGE, "hash").copyright_owner
    assert owner is not None and "acme inc" in owner.lower()


def test_jsonld_and_scripts_do_not_leak_into_text_excerpt() -> None:
    excerpt = extract_html_summary(_PAGE, "hash").text_excerpt or ""
    assert "GTM-" not in excerpt and "Organization" not in excerpt
    assert "Welcome to Acme" in excerpt
