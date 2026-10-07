"""Build evidence-seeking Google (Serper) queries for a domain pair.

Serper is a keyword search, not a classifier: its job is to *retrieve evidence*
about how two domains relate; the LLM then reads that evidence and decides the
category (SAME_AS / PART_OF / ACQUIRED / UNRELATED). So these queries are short,
built from each domain's already-extracted entity name (org name / title / brand)
rather than the raw hostname — a raw infra host like ``x-ui.vercel.app`` is a poor
search term.

Two query shapes:
  * relationship  — both entity names + relationship keywords (acquisition /
                    subsidiary / part of), to surface pages linking the two.
  * identity      — one quoted name + its clean domain + "company", to pull
                    Google's Knowledge Graph (which names an owner/parent) and to
                    disambiguate two different companies that merely share a name.

Pure: no network/DB.
"""

from __future__ import annotations

import re

from domain_resolver.features import normalization as norm
from domain_resolver.matching.views import DomainFeatureView

# Hosting/preview suffixes that are NOT the company's real domain.
_INFRA_SUFFIXES: tuple[str, ...] = (
    ".vercel.app",
    ".webflow.io",
    ".pages.dev",
    ".web.app",
    ".netlify.app",
    ".github.io",
    ".herokuapp.com",
    ".wixsite.com",
    ".firebaseapp.com",
    ".onrender.com",
    ".squarespace.com",
    ".myshopify.com",
)

# Sub-labels that are not the brand when falling back to the hostname.
_GENERIC_LABELS = frozenset({"www", "about", "app", "staging", "dev", "web", "go", "my"})

# Generic UI / boilerplate words that leak into titles and org names; stripped so
# a name like "Ventureprise Hover" becomes "Ventureprise".
_UI_NOISE = frozenset(
    {
        "hover",
        "home",
        "menu",
        "toggle",
        "login",
        "signin",
        "sign",
        "register",
        "skip",
        "content",
        "loading",
        "untitled",
        "welcome",
        "official",
        "site",
        "website",
    }
)

# Title separators: split "Brand | Tagline" -> "Brand".
_SEP_RE = re.compile(r"\s*[|–—·:]\s*|\s+[-]\s+")
_ALPHA_RE = re.compile(r"[a-z]")
_WS_RE = re.compile(r"\s+")

_MAX_NAME_LEN = 60


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _strip_noise(text: str) -> str:
    """Drop generic UI/boilerplate tokens from a candidate name."""
    return " ".join(tok for tok in text.split() if tok.lower() not in _UI_NOISE)


def _ok_name(text: str) -> bool:
    return bool(text) and len(text) <= _MAX_NAME_LEN and len(_ALPHA_RE.findall(text.lower())) >= 2


def _registrable_label(host: str) -> str:
    """Best-effort brand label from a hostname (last-resort fallback)."""
    h = host.lower()
    for suf in _INFRA_SUFFIXES:
        if h.endswith(suf):
            stem = h[: -len(suf)]
            return _clean(stem.split(".")[-1].replace("-", " ")) or host
    parts = [p for p in h.split(".") if p]
    for label in parts:
        if label not in _GENERIC_LABELS:
            return _clean(label.replace("-", " "))
    return _clean(parts[0].replace("-", " ")) if parts else host


def entity_name(view: DomainFeatureView) -> str:
    """The best human-readable entity name for a domain, for use in a search."""
    f = view.features
    for raw in f.org_names:
        name = _strip_noise(_clean(raw))
        if _ok_name(name):
            return name
    if f.normalized_title:
        head = _strip_noise(_clean(_SEP_RE.split(f.normalized_title.strip())[0]))
        if _ok_name(head):
            return head
    for raw in f.brand_keys:
        name = _strip_noise(_clean(raw))
        if _ok_name(name):
            return name
    return _registrable_label(view.host)


def _clean_domain(view: DomainFeatureView) -> str:
    """Prefer a real canonical domain over an infra/preview host."""
    canonical = (view.features.canonical_domain or "").lower()
    if canonical and not any(canonical.endswith(s) for s in _INFRA_SUFFIXES):
        return canonical
    return view.host


def _same_brand(a: DomainFeatureView, b: DomainFeatureView, name_a: str, name_b: str) -> bool:
    """True when the two domains share essentially the SAME brand name/root.

    Deliberately requires an (almost) exact match — shared normalized brand key, or
    equal organization keys after legal/suffix stripping (so "X Holding" and "X
    Group" count as the same root). This is the case where a joint relationship
    query is useless and we must disambiguate each side's identity instead. A mere
    prefix ("Careerly" vs "Careerly Networks") is NOT same-brand: that is a real
    relationship to search for, not a name collision.
    """
    if set(a.features.brand_keys) & set(b.features.brand_keys):
        return True
    ka, kb = norm.organization_key(name_a), norm.organization_key(name_b)
    return bool(ka) and ka == kb


def _quote(name: str) -> str:
    return f'"{name}"' if " " in name else name


def build_relationship_queries(
    view_a: DomainFeatureView, view_b: DomainFeatureView, max_queries: int = 2
) -> list[str]:
    """Return 1-2 Serper queries that surface evidence about the pair's relationship.

    For same-brand pairs (same name, different TLD/host) the relationship query is
    useless, so we emit identity queries for each side instead — this is exactly
    the "same name but possibly different company" case the LLM must disambiguate.
    """
    name_a, name_b = entity_name(view_a), entity_name(view_b)
    dom_a, dom_b = _clean_domain(view_a), _clean_domain(view_b)
    queries: list[str] = []

    if _same_brand(view_a, view_b, name_a, name_b):
        queries.append(f"{_quote(name_a)} ({dom_a}) company")
        if max_queries >= 2:
            queries.append(f"{_quote(name_b)} ({dom_b}) company")
    else:
        queries.append(
            f'{_quote(name_a)} {_quote(name_b)} same company OR acquired OR subsidiary OR "part of"'
        )
        if max_queries >= 2:
            queries.append(f"{_quote(name_b)} ({dom_b}) company")

    # De-duplicate while preserving order, and drop empties.
    seen: set[str] = set()
    out: list[str] = []
    for q in queries[: max(1, max_queries)]:
        q = _clean(q)
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out
