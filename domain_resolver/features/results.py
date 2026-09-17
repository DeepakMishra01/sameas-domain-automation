"""Pydantic contracts for Phase 4 feature extraction output.

A :class:`FeatureSet` is the normalized, versioned representation later phases
consume; :class:`EvidenceDraft` is a single factual, provenance-bearing evidence
record to persist. Nothing here expresses similarity, ownership, or a match.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from domain_resolver.features.errors import ExtractionWarningCategory
from domain_resolver.features.taxonomy import EvidenceCategory, EvidenceReasonCode


class ExtractionWarning(BaseModel):
    category: ExtractionWarningCategory
    detail: str
    field: str | None = None


class CrossDomainReference(BaseModel):
    """A factual reference from the observed domain to another domain."""

    referenced_domain: str
    source_url: str | None = None
    evidence_text: str | None = None


class SocialProfile(BaseModel):
    platform: str
    url: str


class FeatureSet(BaseModel):
    """Deterministic, normalized features for one observation, versioned."""

    feature_version: str
    domain_id: str
    observation_id: str

    normalized_domain: str | None = None
    final_domain: str | None = None

    has_redirect: bool = False
    has_canonical: bool = False
    redirect_target_domain: str | None = None
    canonical_url: str | None = None
    canonical_domain: str | None = None

    normalized_title: str | None = None
    normalized_meta_description: str | None = None
    normalized_text_excerpt: str | None = None
    content_hash: str | None = None
    text_fingerprint: str | None = None
    text_tokens: list[str] = Field(default_factory=list)

    referenced_domains: list[str] = Field(default_factory=list)
    cross_domain_references: list[CrossDomainReference] = Field(default_factory=list)
    social_domains: list[str] = Field(default_factory=list)
    social_profiles: list[SocialProfile] = Field(default_factory=list)
    email_addresses: list[str] = Field(default_factory=list)
    email_domains: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)  # unsupported today; see taxonomy

    dns_a: list[str] = Field(default_factory=list)
    dns_aaaa: list[str] = Field(default_factory=list)
    dns_cname: list[str] = Field(default_factory=list)
    dns_mx: list[str] = Field(default_factory=list)
    dns_ns: list[str] = Field(default_factory=list)


class EvidenceDraft(BaseModel):
    """A single factual evidence record with provenance, ready to persist."""

    reason_code: EvidenceReasonCode
    category: EvidenceCategory
    source_url: str | None = None
    evidence_text: str | None = None
    referenced_domain: str | None = None
    raw_value: str | None = None
    raw_payload: dict[str, object] = Field(default_factory=dict)


class ExtractionOutput(BaseModel):
    """The full pure-extraction result before persistence."""

    features: FeatureSet
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
