"""Structured verdict for the Geographies Served task."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GeoVerdict(BaseModel):
    """The countries a company operates in / serves, read from evidence.

    ``countries`` is the list the model extracted from the website and web search
    evidence; the Single / Multinational / Global category is computed separately
    and deterministically from this list (see :mod:`domain_resolver.geo.category`).
    """

    countries: list[str] = Field(default_factory=list)
    headquarters: str | None = None
    evidence_quote: str = ""
    reasoning: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model: str = ""
