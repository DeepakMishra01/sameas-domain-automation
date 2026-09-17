"""Unit tests for the deterministic feature extractor (no network/DB)."""

from datetime import UTC, datetime
from uuid import uuid4

from domain_resolver.features.errors import ExtractionWarningCategory
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.features.taxonomy import EvidenceReasonCode
from domain_resolver.observation.results import (
    DnsObservation,
    DnsRecordSet,
    HtmlSummary,
    HttpObservation,
    ObservationResult,
    RedirectHop,
)

VERSION = "feature-extractor-test"


def _result(
    *,
    links: list[str] | None = None,
    text: str = "Welcome to Acme. Contact hello@acme.com",
    redirect: bool = False,
    dns: bool = True,
) -> ObservationResult:
    html = HtmlSummary(
        title="Acme Inc | Home",
        meta_description="Best acme widgets",
        canonical_url="https://acme.com/",
        links=links if links is not None else [],
        text_excerpt=text,
        content_hash="deadbeef",
    )
    chain = (
        [
            RedirectHop(
                source_url="https://acme.com/",
                status_code=301,
                location="https://www.acme.com/",
                target_url="https://www.acme.com/",
            )
        ]
        if redirect
        else []
    )
    http = HttpObservation(
        requested_url="https://acme.com/",
        status_code=200,
        content_type="text/html",
        final_url="https://acme.com/",
        final_hostname="acme.com",
        redirect_chain=chain,
        html=html,
    )
    records = (
        [
            DnsRecordSet(record_type="A", values=["1.2.3.4"]),
            DnsRecordSet(record_type="MX", values=["10 mail.acme.com."]),
        ]
        if dns
        else []
    )
    return ObservationResult(
        collector_version="v",
        observed_at=datetime.now(UTC),
        dns=DnsObservation(hostname="acme.com", records=records),
        http=http,
    )


def _extract(result: ObservationResult) -> object:
    return FeatureExtractor(VERSION).extract(
        domain_id=uuid4(),
        observation_id=uuid4(),
        domain_host="acme.com",
        result=result,
    )


def test_extracts_website_and_content_features() -> None:
    out = _extract(_result())
    f = out.features
    assert f.feature_version == VERSION
    assert f.normalized_domain == "acme.com"
    assert f.normalized_title == "acme inc | home"
    assert f.normalized_meta_description == "best acme widgets"
    assert f.has_canonical is True
    assert f.canonical_domain == "acme.com"
    assert f.content_hash == "deadbeef"
    assert f.text_fingerprint is not None
    assert "welcome" in f.text_tokens
    assert f.email_addresses == ["hello@acme.com"]
    assert f.email_domains == ["acme.com"]


def test_links_classification() -> None:
    links = [
        "https://partner.io/x",
        "https://www.linkedin.com/company/acme/",
        "/about",  # same-site relative
        "https://blog.acme.com/post",  # same-site subdomain
        "mailto:sales@acme.com",
        "tel:+1 415 555 2671",
    ]
    out = _extract(_result(links=links))
    f = out.features
    assert f.referenced_domains == ["partner.io"]
    assert [p.platform for p in f.social_profiles] == ["linkedin"]
    assert f.social_domains == ["linkedin.com"]
    assert f.email_addresses == ["hello@acme.com", "sales@acme.com"]
    assert f.phone_numbers == ["+14155552671"]


def test_dns_features_and_evidence() -> None:
    out = _extract(_result())
    f = out.features
    assert f.dns_a == ["1.2.3.4"]
    assert f.dns_mx == ["10 mail.acme.com."]
    codes = {e.reason_code for e in out.evidence}
    assert EvidenceReasonCode.DNS_A in codes
    assert EvidenceReasonCode.DNS_MX in codes


def test_evidence_has_provenance_and_expected_codes() -> None:
    out = _extract(_result(links=["https://partner.io/x"]))
    codes = {e.reason_code for e in out.evidence}
    assert {
        EvidenceReasonCode.TITLE,
        EvidenceReasonCode.META_DESCRIPTION,
        EvidenceReasonCode.CANONICAL_URL,
        EvidenceReasonCode.CONTENT_HASH,
        EvidenceReasonCode.CONTENT_TEXT,
        EvidenceReasonCode.CROSS_DOMAIN_REFERENCE,
        EvidenceReasonCode.EMAIL_DOMAIN,
    }.issubset(codes)
    cross = next(
        e for e in out.evidence if e.reason_code == EvidenceReasonCode.CROSS_DOMAIN_REFERENCE
    )
    assert cross.referenced_domain == "partner.io"
    assert cross.source_url == "https://acme.com/"
    assert cross.evidence_text == "https://partner.io/x"


def test_redirect_evidence() -> None:
    out = _extract(_result(redirect=True))
    assert out.features.has_redirect is True
    assert any(e.reason_code == EvidenceReasonCode.REDIRECT for e in out.evidence)


def test_extraction_is_deterministic() -> None:
    result = _result(links=["https://b.io/2", "https://a.io/1", "https://www.linkedin.com/x"])
    first = _extract(result).features.model_dump()
    second = _extract(result).features.model_dump()
    # domain_id/observation_id differ per call; compare the extracted signal only.
    for key in ("referenced_domains", "social_domains", "email_addresses", "dns_a", "text_tokens"):
        assert first[key] == second[key]
    assert first["referenced_domains"] == ["a.io", "b.io"]  # sorted, deterministic


def test_malformed_email_and_phone_produce_warnings() -> None:
    out = _extract(_result(links=["mailto:not-an-email", "tel:12"], text="no email here"))
    categories = {w.category for w in out.warnings}
    assert ExtractionWarningCategory.INVALID_EMAIL in categories
    assert ExtractionWarningCategory.INVALID_PHONE in categories


def test_oversized_links_warns_and_bounds() -> None:
    links = [f"https://ref{i}.example/x" for i in range(300)]
    out = _extract(_result(links=links))
    assert any(w.category == ExtractionWarningCategory.OVERSIZED_FIELD for w in out.warnings)
    assert len(out.features.referenced_domains) <= 200


def test_unicode_text_is_normalized() -> None:
    out = _extract(_result(text="Café Résumé ＡＢＣ"))
    assert out.features.normalized_text_excerpt == "café résumé abc"
