"""Prompt construction for the Geographies Served LLM step.

Feeds the model the facts already observed from the company's website (title,
description, on-page addresses, page text) plus optional web search results
(Google / Wikipedia snippets), and asks for the list of countries the company
operates in or serves. The category is computed in code, not by the model.
"""

from __future__ import annotations

from domain_resolver.matching.views import DomainFeatureView

_EXCERPT_CHARS = 1500

SYSTEM_PROMPT = """You are a precise analyst finding the GEOGRAPHIES (countries) a \
company operates in or serves, for a company-profiling team. You are given facts \
observed from the company's own website, plus web search results (which may include \
Wikipedia and Google snippets).

List every country where the company has a real presence: offices, operations, \
manufacturing, or where its product/service is actually offered. Use the full \
country name (e.g. "United States", "United Kingdom", "India").

Rules:
- Base the answer ONLY on the provided evidence. Do not guess from the brand name.
- Include a country only if the evidence shows real presence or service there \
(offices, operations, or where the product/service is offered). A shipping or \
currency list is weaker than stated offices or operations.
- HEADQUARTERS: find the HQ country from the website, the LinkedIn "Headquarters" \
line, or the Wikipedia infobox. Put it in "headquarters" AND include it in "countries".
- A company always operates in at least its headquarters country, so "countries" \
should NOT be empty when any HQ or office location is known. Return an empty list \
only when there is truly no location evidence at all.
- Use the LinkedIn "Locations" and the Wikipedia infobox to add more countries.
- Always include a short evidence_quote copied from the provided facts.
- confidence is 0.0-1.0 (how sure you are about the country list).

Respond with ONLY a JSON object of this exact shape and nothing else:
{"countries": ["..."], "headquarters": "..."|null, "evidence_quote": "...", \
"reasoning": "one or two sentences", "confidence": 0.0}"""


def _facts(view: DomainFeatureView, company_name: str) -> str:
    f = view.features
    lines = []
    if company_name:
        lines.append(f"company: {company_name}")
    lines.append(f"domain: {view.host}")
    if f.normalized_title:
        lines.append(f"title: {f.normalized_title}")
    if f.normalized_meta_description:
        lines.append(f"description: {f.normalized_meta_description[:300]}")
    if f.addresses:
        lines.append(f"addresses_on_site: {' | '.join(f.addresses[:8])}")
    if f.org_names:
        lines.append(f"names_on_site: {', '.join(f.org_names[:5])}")
    if f.normalized_text_excerpt:
        lines.append(f"page_text: {f.normalized_text_excerpt[:_EXCERPT_CHARS]}")
    return "\n".join(lines)


def build_user_prompt(
    view: DomainFeatureView, company_name: str = "", web_evidence: str = ""
) -> str:
    parts = ["COMPANY WEBSITE FACTS", _facts(view, company_name)]
    if web_evidence:
        parts += [
            "",
            "WEB SEARCH RESULTS (Google / LinkedIn / Wikipedia - use the Headquarters and "
            "Locations lines to find the HQ and the countries; ignore anything irrelevant):",
            web_evidence[:1800],
        ]
    label = company_name or view.host
    parts += [
        "",
        f"Question: Which countries does {label} operate in or serve? " "Return only the JSON.",
    ]
    return "\n".join(parts)
