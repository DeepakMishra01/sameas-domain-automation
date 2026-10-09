"""Deterministic Single / Multinational / Global categorisation.

Per the Geos Served rulebook:
  * Single Geo     - serves only one country
  * Multinational  - more than one country (but under the global threshold)
  * IsGlobal       - 50+ countries across major continents
  * Unknown        - no country evidence (route to review)

The country LIST comes from the LLM reading the evidence; the category is computed
here from that list, so the label is auditable and never a model guess.
"""

from __future__ import annotations

SINGLE = "Single Geo"
MULTINATIONAL = "Multinational"
GLOBAL = "IsGlobal"
UNKNOWN = "Unknown"

_GLOBAL_THRESHOLD = 50


def _normalise(countries: list[str]) -> set[str]:
    return {c.strip().lower() for c in countries if c and c.strip()}


def categorize(countries: list[str]) -> str:
    """Map a list of country names to a geo category by distinct-country count."""
    count = len(_normalise(countries))
    if count == 0:
        return UNKNOWN
    if count == 1:
        return SINGLE
    if count >= _GLOBAL_THRESHOLD:
        return GLOBAL
    return MULTINATIONAL


def country_count(countries: list[str]) -> int:
    return len(_normalise(countries))
