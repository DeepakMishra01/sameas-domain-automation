"""Prompt construction for the LLM relationship verifier.

Feeds the model only ALREADY-OBSERVED, stored facts about the two domains (title,
meta, a bounded text excerpt, outbound links, redirect/canonical facts, extracted
names) — never re-crawls. The model must ground its verdict in a quoted piece of
that evidence.
"""

from __future__ import annotations

from domain_resolver.matching.views import DomainFeatureView

_EXCERPT_CHARS = 1200

SYSTEM_PROMPT = """You are a precise analyst deciding the business relationship \
between TWO web domains for a company-profiling team. You are given facts already \
observed from each site (title, description, page text, links, redirect/canonical \
info, extracted names). Decide ONE relationship and ground it in a quote.

Categories:
- SAME_AS: the two domains are the SAME single company/brand/entity (e.g. the same \
brand on two TLDs, a rebrand, or one is just a mirror of the other).
- PART_OF: one domain is a product, brand, subsidiary, division, service, or \
regional entity OF the other (they belong to one organisation but are distinct). \
Give a subtype: PRODUCT, BRAND, SUBSIDIARY, BUSINESS_UNIT, SERVICE, DIVISION, \
REGIONAL_ENTITY, or OTHER.
- ACQUIRED: one company acquired the other, and the acquired one is still a \
distinct entity/site.
- UNRELATED: there is NO real organisational relationship. IMPORTANT: a shop that \
merely SELLS ON a marketplace, or a site merely BUILT ON / HOSTED BY a platform, is \
UNRELATED to that marketplace/platform — sharing a platform's name in the footer is \
NOT a relationship. Two different companies with a similar name are UNRELATED. Also \
UNRELATED: if one or both pages are a PARKED / "domain for sale" / expired-domain / \
broker page, or a hosting-provider or default-server placeholder (e.g. seghost, sedo, \
parkingcrew, bodis, hugedomains, "welcome to nginx", "default web page"), the shared \
content is the HOST or BROKER, not the two businesses — do NOT call it PART_OF/SAME_AS.
- REVIEW_REQUIRED: the evidence is genuinely contradictory or insufficient to decide.

Rules:
- Base the decision only on the provided facts. If they are too thin, choose \
REVIEW_REQUIRED — do not guess.
- For SAME_AS, PART_OF and ACQUIRED, set primary_domain (the parent / acquirer / \
surviving brand) and secondary_domain (the child / acquired / alias).
- Always include evidence_quote: a short exact snippet from the provided facts that \
supports the decision (empty only for REVIEW_REQUIRED/UNRELATED when nothing links them).
- confidence is 0.0-1.0.

Sector rule:
- If a sector for DOMAIN A is given, judge whether DOMAIN B operates in the SAME \
broad sector/industry (allow for different wording of the same space). Set \
"same_sector" true/false accordingly (null if no sector was given or you cannot \
tell). Two domains in clearly DIFFERENT sectors are NOT the same company: never \
answer SAME_AS in that case (they may still be UNRELATED or, rarely, PART_OF).

Respond with ONLY a JSON object of this exact shape and nothing else:
{"relationship_type": "...", "relationship_subtype": "..."|null, "primary_domain": \
"..."|null, "secondary_domain": "..."|null, "evidence_quote": "...", "reasoning": \
"one or two sentences", "confidence": 0.0, "same_sector": true|false|null}"""


def _facts(view: DomainFeatureView) -> str:
    f = view.features
    lines = [f"domain: {view.host}"]
    if f.normalized_title:
        lines.append(f"title: {f.normalized_title}")
    if f.normalized_meta_description:
        lines.append(f"description: {f.normalized_meta_description[:300]}")
    if f.org_names:
        lines.append(f"names_on_site: {', '.join(f.org_names[:5])}")
    if f.has_redirect and f.redirect_target_domain:
        lines.append(f"redirects_to: {f.redirect_target_domain}")
    if f.canonical_domain:
        lines.append(f"canonical_domain: {f.canonical_domain}")
    if f.referenced_domains:
        lines.append(f"links_to: {', '.join(sorted(set(f.referenced_domains))[:8])}")
    if f.normalized_text_excerpt:
        lines.append(f"page_text: {f.normalized_text_excerpt[:_EXCERPT_CHARS]}")
    return "\n".join(lines)


def build_user_prompt(
    view_a: DomainFeatureView,
    view_b: DomainFeatureView,
    deterministic_hint: str = "",
    web_evidence: str = "",
    domain_a_sector: str = "",
) -> str:
    facts_a = _facts(view_a)
    if domain_a_sector:
        facts_a += f"\nsector: {domain_a_sector}"
    parts = ["DOMAIN A", facts_a, "", "DOMAIN B", _facts(view_b)]
    if web_evidence:
        parts += [
            "",
            "WEB SEARCH RESULTS (external context — use to confirm ownership/acquisition/"
            "part-of that the pages alone don't show; ignore if irrelevant):",
            web_evidence[:1500],
        ]
    if deterministic_hint:
        parts += ["", f"(automated guess, may be wrong: {deterministic_hint})"]
    parts += [
        "",
        "Question: Are DOMAIN A and DOMAIN B related? If yes, classify HOW: SAME_AS "
        "(the same entity, or one redirects to the other), PART_OF (one is a product / "
        "brand / subsidiary / division / regional site of the other), or ACQUIRED (one "
        "company acquired the other). If they only share the same or a similar NAME but are "
        "actually different, independent companies, answer UNRELATED. If the evidence is "
        "genuinely insufficient or contradictory, answer REVIEW_REQUIRED. Return only the JSON.",
    ]
    return "\n".join(parts)
