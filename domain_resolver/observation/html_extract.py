"""Bounded, deterministic HTML fact extraction.

Uses the standard-library HTML parser (no external parser, no JavaScript
execution) to collect only the bounded facts later phases need: title, meta
description, canonical URL, links, a bounded text excerpt, a content hash, and
(Stage 2) bounded *identity* facts — OpenGraph site/name, JSON-LD organization
names, favicon reference, analytics identifiers, and a copyright owner.

It deliberately does NOT extract or classify company identity, legal entity,
same-as relationships, or any primary/secondary judgement — that is the job of
the extraction and matching phases. Every field here is a raw observed fact.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from domain_resolver.observation.limits import DEFAULT_LIMITS, ObservationLimits
from domain_resolver.observation.results import HtmlSummary

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})
_FAVICON_RELS = frozenset({"icon", "apple-touch-icon", "mask-icon"})
_JSONLD_ORG_TYPES = ("organization", "corporation", "company", "localbusiness", "brand", "website")
_MAX_ANALYTICS = 20
_MAX_JSONLD_NAMES = 10

# Analytics / tag-manager identifiers, matched over the raw body. Each is a
# stable, operator-assigned identifier — never a per-page value.
_ANALYTICS_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bUA-\d{4,10}-\d{1,4}\b"),
    re.compile(r"\bG-[A-Z0-9]{6,12}\b"),
    re.compile(r"\bGTM-[A-Z0-9]{4,10}\b"),
    re.compile(r"\bAW-\d{6,12}\b"),
)
_COPYRIGHT_RE = re.compile(
    r"(?:©|&copy;|copyright)\s*(?:\(c\)\s*)?(?:\d{4}\s*(?:[-–]\s*\d{4})?\s*)?(?:by\s+)?"
    r"([A-Za-z0-9][^.,|©\n\r<>{}]{1,60})",
    re.IGNORECASE,
)
_COPYRIGHT_TAIL_RE = re.compile(r"\s+all rights reserved.*$", re.IGNORECASE)


def _parse_refresh_target(content: str) -> str | None:
    """Extract the URL from a ``<meta http-equiv="refresh">`` content value."""
    _, _, directive = content.partition(";")
    directive = directive.strip()
    if directive[:4].lower() != "url=":
        return None
    target = directive[4:].strip().strip("'\"")
    return target or None


def _extract_jsonld_names(raw: str) -> list[str]:
    """Return organization/brand names from one JSON-LD script block (bounded)."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    names: list[str] = []

    def walk(node: Any) -> None:
        if len(names) >= _MAX_JSONLD_NAMES:
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        types = node.get("@type", "")
        type_text = " ".join(types if isinstance(types, list) else [str(types)]).lower()
        if any(t in type_text for t in _JSONLD_ORG_TYPES):
            for key in ("name", "legalName", "alternateName"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    cleaned = value.strip()
                    if cleaned not in names:
                        names.append(cleaned)
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value)

    walk(data)
    return names[:_MAX_JSONLD_NAMES]


def _extract_analytics_ids(raw: str) -> list[str]:
    found: list[str] = []
    for pattern in _ANALYTICS_RES:
        for match in pattern.findall(raw):
            if match not in found:
                found.append(match)
            if len(found) >= _MAX_ANALYTICS:
                return sorted(found)
    return sorted(found)


def _extract_copyright_owner(raw: str) -> str | None:
    match = _COPYRIGHT_RE.search(raw)
    if match is None:
        return None
    owner = _COPYRIGHT_TAIL_RE.sub("", match.group(1)).strip(" -–|·").strip()
    # Strip a leading year the year-skip did not consume, then require a real name
    # (>= 3 letters) so a bare "2024" is never captured as an owner.
    owner = re.sub(r"^(?:\(c\)\s*)?(?:19|20)\d{2}\s*", "", owner).strip()
    if len(re.findall(r"[A-Za-z]", owner)) < 3:
        return None
    return owner or None


class _BoundedHtmlParser(HTMLParser):
    def __init__(self, limits: ObservationLimits) -> None:
        super().__init__(convert_charrefs=True)
        self._limits = limits
        self.title_parts: list[str] = []
        self.meta_description: str | None = None
        self.og_description: str | None = None
        self.og_site_name: str | None = None
        self.og_title: str | None = None
        self.canonical_url: str | None = None
        self.favicon_href: str | None = None
        self.meta_refresh_url: str | None = None
        self.links: list[str] = []
        self.jsonld_names: list[str] = []
        self._text_parts: list[str] = []
        self._text_len = 0
        self.truncated = False
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            if tag == "script":
                attributes = {key.lower(): (value or "") for key, value in attrs}
                if attributes.get("type", "").lower() == "application/ld+json":
                    self._in_jsonld = True
                    self._jsonld_parts = []
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            name = attributes.get("name", "").lower()
            prop = attributes.get("property", "").lower()
            http_equiv = attributes.get("http-equiv", "").lower()
            content = attributes.get("content")
            if name == "description" and content:
                self.meta_description = self.meta_description or content.strip()
            elif prop == "og:description" and content:
                self.og_description = self.og_description or content.strip()
            elif prop == "og:site_name" and content:
                self.og_site_name = self.og_site_name or content.strip()
            elif prop == "og:title" and content:
                self.og_title = self.og_title or content.strip()
            elif http_equiv == "refresh" and content and self.meta_refresh_url is None:
                self.meta_refresh_url = _parse_refresh_target(content)
        elif tag == "link":
            rel_tokens = attributes.get("rel", "").lower().split()
            href = attributes.get("href")
            if "canonical" in rel_tokens and href and self.canonical_url is None:
                self.canonical_url = href.strip()
            if (
                self.favicon_href is None
                and href
                and any(token in _FAVICON_RELS for token in rel_tokens)
            ):
                self.favicon_href = href.strip()
        elif tag == "a":
            href = attributes.get("href")
            if href and len(self.links) < self._limits.max_links:
                cleaned = href.strip()
                if cleaned and cleaned not in self.links:
                    self.links.append(cleaned)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            if tag == "script" and self._in_jsonld:
                for name in _extract_jsonld_names("".join(self._jsonld_parts)):
                    if name not in self.jsonld_names and len(self.jsonld_names) < _MAX_JSONLD_NAMES:
                        self.jsonld_names.append(name)
                self._in_jsonld = False
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_jsonld:
            self._jsonld_parts.append(data)
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
    # Analytics IDs and copyright are scanned over the raw body (they live in
    # inline scripts / footers that the text extractor deliberately skips).
    return HtmlSummary(
        title=title,
        meta_description=parser.meta_description or parser.og_description,
        canonical_url=parser.canonical_url,
        meta_refresh_url=parser.meta_refresh_url,
        links=parser.links,
        text_excerpt=text_excerpt,
        content_hash=content_hash,
        truncated=parser.truncated,
        og_site_name=parser.og_site_name,
        og_title=parser.og_title,
        favicon_href=parser.favicon_href,
        analytics_ids=_extract_analytics_ids(text),
        jsonld_names=parser.jsonld_names,
        copyright_owner=_extract_copyright_owner(text),
    )
