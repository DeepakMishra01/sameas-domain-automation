"""Bounded, deterministic HTML fact extraction.

Uses the standard-library HTML parser (no external parser, no JavaScript
execution) to collect only the bounded facts later phases need: title, meta
description, canonical URL, links, a bounded text excerpt, and a content hash.

It deliberately does NOT extract or classify company identity, legal entity,
same-as relationships, or any primary/secondary judgement — that is the job of
the extraction and matching phases.
"""

from __future__ import annotations

from html.parser import HTMLParser

from domain_resolver.observation.limits import DEFAULT_LIMITS, ObservationLimits
from domain_resolver.observation.results import HtmlSummary

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})


class _BoundedHtmlParser(HTMLParser):
    def __init__(self, limits: ObservationLimits) -> None:
        super().__init__(convert_charrefs=True)
        self._limits = limits
        self.title_parts: list[str] = []
        self.meta_description: str | None = None
        self.og_description: str | None = None
        self.canonical_url: str | None = None
        self.links: list[str] = []
        self._text_parts: list[str] = []
        self._text_len = 0
        self.truncated = False
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            name = attributes.get("name", "").lower()
            prop = attributes.get("property", "").lower()
            content = attributes.get("content")
            if name == "description" and content:
                self.meta_description = self.meta_description or content.strip()
            elif prop == "og:description" and content:
                self.og_description = self.og_description or content.strip()
        elif tag == "link":
            rel = attributes.get("rel", "").lower()
            href = attributes.get("href")
            if "canonical" in rel.split() and href and self.canonical_url is None:
                self.canonical_url = href.strip()
        elif tag == "a":
            href = attributes.get("href")
            if href and len(self.links) < self._limits.max_links:
                cleaned = href.strip()
                if cleaned and cleaned not in self.links:
                    self.links.append(cleaned)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (e.g. <meta .../>, <link .../>) must still be inspected.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if not stripped:
            return
        remaining = self._limits.max_text_chars - self._text_len
        if remaining <= 0:
            self.truncated = True
            return
        chunk = stripped[:remaining]
        self._text_parts.append(chunk)
        self._text_len += len(chunk)
        if len(stripped) > remaining:
            self.truncated = True


def extract_html_summary(
    text: str,
    content_hash: str | None,
    limits: ObservationLimits = DEFAULT_LIMITS,
) -> HtmlSummary:
    """Extract bounded HTML facts. Raises ``ValueError`` only on parser failure."""
    parser = _BoundedHtmlParser(limits)
    parser.feed(text)
    parser.close()

    title = " ".join(" ".join(parser.title_parts).split()) or None
    text_excerpt = " ".join(" ".join(parser._text_parts).split()) or None
    return HtmlSummary(
        title=title,
        meta_description=parser.meta_description or parser.og_description,
        canonical_url=parser.canonical_url,
        links=parser.links,
        text_excerpt=text_excerpt,
        content_hash=content_hash,
        truncated=parser.truncated,
    )
