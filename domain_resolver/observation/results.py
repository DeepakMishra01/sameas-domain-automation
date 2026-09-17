"""Structured, serialisable results produced by the observers.

These are pure factual records — "what did we observe?" — and never carry any
relationship, ownership, or ranking judgement. They serialise to JSON for
persistence in ``domain_observations.payload`` and for API responses.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from domain_resolver.models.entities import ObservationErrorCategory


class DnsRecordSet(BaseModel):
    """The values observed for a single DNS record type."""

    record_type: str
    values: list[str] = Field(default_factory=list)
    error: str | None = None


class DnsObservation(BaseModel):
    hostname: str
    records: list[DnsRecordSet] = Field(default_factory=list)
    error_category: ObservationErrorCategory | None = None
    error_detail: str | None = None


class RedirectHop(BaseModel):
    """A single hop in an HTTP redirect chain, recorded as fact only."""

    source_url: str
    status_code: int
    location: str
    target_url: str


class HtmlSummary(BaseModel):
    """Bounded HTML facts needed by later phases; no identity interpretation."""

    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    links: list[str] = Field(default_factory=list)
    text_excerpt: str | None = None
    content_hash: str | None = None
    truncated: bool = False


class HttpObservation(BaseModel):
    requested_url: str
    scheme_attempts: list[str] = Field(default_factory=list)
    status_code: int | None = None
    http_version: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    content_type: str | None = None
    response_size_bytes: int | None = None
    elapsed_ms: float | None = None
    redirect_chain: list[RedirectHop] = Field(default_factory=list)
    final_url: str | None = None
    final_hostname: str | None = None
    html: HtmlSummary | None = None
    error_category: ObservationErrorCategory | None = None
    error_detail: str | None = None


class ObservationResult(BaseModel):
    """The complete factual snapshot for one observation run."""

    collector_version: str
    observed_at: datetime
    dns: DnsObservation
    http: HttpObservation

    @property
    def error_category(self) -> ObservationErrorCategory | None:
        """The most informative single error category for the whole run."""
        return self.http.error_category or self.dns.error_category
