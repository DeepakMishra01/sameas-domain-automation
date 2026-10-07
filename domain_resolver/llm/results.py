"""Structured verdict returned by the LLM relationship verifier."""

from __future__ import annotations

from pydantic import BaseModel, Field

from domain_resolver.classification.relationship_types import PartOfSubtype, RelationshipType


class AiVerdict(BaseModel):
    """An LLM's reasoned relationship judgement for one domain pair.

    The verdict is *advisory*: the pipeline keeps deterministic, evidence-backed
    results (a real redirect, a matching name, an explicit statement) authoritative
    and uses the LLM only for the uncertain/assumed pairs. Every verdict carries a
    quoted piece of evidence so a human can audit it.
    """

    relationship_type: RelationshipType
    relationship_subtype: PartOfSubtype | None = None
    primary_domain: str | None = None
    secondary_domain: str | None = None
    evidence_quote: str = ""
    reasoning: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model: str = ""
    # Whether the two domains are in the same broad sector/industry. Only meaningful
    # when a Domain-1 feed sector was supplied. None = not assessed. False forbids a
    # non-redirect SAME_AS (two different sectors cannot be the same company).
    same_sector: bool | None = None
