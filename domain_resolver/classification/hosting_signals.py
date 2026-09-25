"""Hosting-provider / parked / for-sale / broker page detection.

Some candidate pairs are linked only because both domains are served by the same
hosting provider, sit on the same domain-parking service, or show a "this domain
is for sale" broker page. In that case the shared "brand/identity" is the *host or
broker* — not a real organisational relationship between the two businesses. Many
differently-named domains all parked on / hosted by one provider are NOT part of
one company.

This module detects such placeholder pages from the already-observed Phase 4
facts (title, meta, text excerpt, extracted names). It is intentionally
high-precision: it only fires on explicit for-sale/parked/placeholder wording or a
known parking/broker/host brand, so a real business page is not mistaken for one.

Pure: no network/DB.
"""

from __future__ import annotations

import re

from domain_resolver.matching.views import DomainFeatureView

# Explicit "this domain is for sale / parked / expired" wording. High precision:
# a genuine company homepage does not say these things about itself.
_FOR_SALE_OR_PARKED: tuple[str, ...] = (
    "domain is for sale",
    "this domain is for sale",
    "domain for sale",
    "domain name is for sale",
    "buy this domain",
    "purchase this domain",
    "inquire about this domain",
    "this domain is parked",
    "parked domain",
    "domain parking",
    "this page is parked",
    "this domain has expired",
    "the domain has expired",
    "domain has expired and is pending renewal",
)

# Default web-server / provisioning placeholder pages.
_PLACEHOLDER: tuple[str, ...] = (
    "welcome to nginx",
    "apache2 ubuntu default page",
    "apache http server test page",
    "default web page",
    "future home of something",
    "website is not configured",
    "site not configured",
)

# Known domain-parking / broker / host brands. When one of these is the shared
# identity, the link is the provider, not the two businesses. Matched as whole
# words in the page text and against extracted org/brand names.
_BROKER_HOST_BRANDS: frozenset[str] = frozenset(
    {
        "seghost",
        "sedo",
        "sedoparking",
        "parkingcrew",
        "bodis",
        "hugedomains",
        "afternic",
        "undeveloped",
        "dan.com",
        "namebright",
        "domainmarket",
        "buydomains",
        "namecheap",
        "godaddy",
    }
)

# Distinctive broker/parking tokens safe to match anywhere in the body text
# (unlikely to be a substring of an unrelated word).
_BROKER_TOKEN_RE = re.compile(r"\b(seghost|sedoparking|parkingcrew|hugedomains|afternic|bodis)\b")


def is_hosting_or_parked(view: DomainFeatureView) -> bool:
    """True if the page is a parked / for-sale / broker / host placeholder.

    Uses only already-observed facts. Any true result means a shared "identity"
    with the peer is spurious (it belongs to the host/broker), so the pair is not
    a genuine business relationship.
    """
    f = view.features
    blob = " ".join(
        part.lower()
        for part in (
            f.normalized_title,
            f.normalized_meta_description,
            f.normalized_text_excerpt,
        )
        if part
    )
    if any(phrase in blob for phrase in _FOR_SALE_OR_PARKED):
        return True
    if any(phrase in blob for phrase in _PLACEHOLDER):
        return True
    names = {n.lower() for n in (*f.org_names, *f.brand_keys)}
    if names & _BROKER_HOST_BRANDS:
        return True
    return bool(_BROKER_TOKEN_RE.search(blob))
