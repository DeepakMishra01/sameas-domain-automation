"""Deterministic feature/evidence extraction from a persisted observation.

Pure and reproducible: no network, DNS, clock, or database access. Given a Phase
3 :class:`ObservationResult` it returns normalized features, factual evidence
drafts (each with provenance), and structured warnings. It makes no judgement
about whether domains are related — that is Phase 5.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from domain_resolver.features import normalization as norm
from domain_resolver.features.errors import ExtractionWarningCategory
from domain_resolver.features.results import (
    CrossDomainReference,
    EvidenceDraft,
    ExtractionOutput,
    ExtractionWarning,
    FeatureSet,
    SocialProfile,
)
from domain_resolver.features.taxonomy import (
    CATEGORY_OF,
    DNS_CODE_BY_RECORD_TYPE,
    EvidenceReasonCode,
)
from domain_resolver.observation.results import ObservationResult

_MAX_LIST = 200
_MAX_TEXT = 20_000


class FeatureExtractor:
    """Extract deterministic features and factual evidence from an observation."""

    def __init__(self, version: str) -> None:
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def extract(
        self,
        *,
        domain_id: UUID,
        observation_id: UUID,
        domain_host: str,
        result: ObservationResult,
    ) -> ExtractionOutput:
        warnings: list[ExtractionWarning] = []
        evidence: list[EvidenceDraft] = []

        source_host = self._normalize_host(domain_host, warnings, field="domain")
        features = FeatureSet(
            feature_version=self._version,
            domain_id=str(domain_id),
            observation_id=str(observation_id),
            normalized_domain=source_host,
        )

        self._extract_http(result, features, evidence, warnings, source_host)
        self._extract_dns(result, features, evidence)
        self._extract_identity(result, features, evidence, source_host)

        return ExtractionOutput(features=features, evidence=evidence, warnings=warnings)

    # -- Stage 2 identity signals --------------------------------------------

    def _extract_identity(
        self,
        result: ObservationResult,
        features: FeatureSet,
        evidence: list[EvidenceDraft],
        source_host: str | None,
    ) -> None:
        """Populate brand/organization and technical fingerprint identity facts.

        Runs regardless of HTML so TLS facts are captured for HTTP-only or
        non-HTML hosts too. All outputs are supporting identity evidence and never
        assert that two domains are the same entity.
        """
        http = result.http
        page_url = http.final_url or http.requested_url
        html = http.html

        names: list[str] = []
        if html is not None:
            # NB: og:title is a *page title*, not an organization name, and is
            # intentionally excluded (the <title>-derived brand key already covers
            # title text below).
            for raw in (html.og_site_name, *html.jsonld_names, html.copyright_owner):
                if not raw:
                    continue
                name = norm.normalize_text(raw)
                # Require a real name (>= 3 letters) so a bare year/number that
                # slipped through never becomes an organization-name signal.
                if (
                    name
                    and sum(c.isalpha() for c in name) >= 3
                    and name not in names
                    and len(names) < _MAX_LIST
                ):
                    names.append(name)
            if html.copyright_owner:
                features.copyright_owner = norm.normalize_text(html.copyright_owner) or None
            if html.favicon_href:
                features.favicon_href = html.favicon_href[:_MAX_TEXT]
            for aid in html.analytics_ids[:_MAX_LIST]:
                bucket = features.gtm_ids if aid.startswith("GTM-") else features.analytics_ids
                if aid not in bucket:
                    bucket.append(aid)
        features.org_names = names

        brand_keys: list[str] = []
        brand_sources = [*names]
        if features.normalized_title:
            brand_sources.append(features.normalized_title)
        if source_host:
            brand_sources.append(norm.domain_name_key(source_host))
        for src in brand_sources:
            key = norm.organization_key(src)
            if key and key not in brand_keys:
                brand_keys.append(key)
        features.brand_keys = brand_keys

        features.tls_sans = list(http.tls_sans)
        features.tls_fingerprint = http.tls_fingerprint

        self._emit_identity_evidence(features, evidence, page_url)

    def _emit_identity_evidence(
        self, features: FeatureSet, evidence: list[EvidenceDraft], page_url: str | None
    ) -> None:
        def add(code: EvidenceReasonCode, value: str) -> None:
            evidence.append(
                EvidenceDraft(
                    reason_code=code,
                    category=CATEGORY_OF[code],
                    source_url=page_url,
                    evidence_text=value[:_MAX_TEXT],
                    raw_value=value[:_MAX_TEXT],
                )
            )

        for name in features.org_names:
            add(EvidenceReasonCode.ORGANIZATION_NAME, name)
        for key in features.brand_keys:
            add(EvidenceReasonCode.BRAND_NAME, key)
        if features.copyright_owner:
            add(EvidenceReasonCode.COPYRIGHT_OWNER, features.copyright_owner)
        for aid in features.analytics_ids:
            add(EvidenceReasonCode.ANALYTICS_ID, aid)
        for gid in features.gtm_ids:
            add(EvidenceReasonCode.GTM_ID, gid)
        for san in features.tls_sans[:_MAX_LIST]:
            add(EvidenceReasonCode.TLS_SAN, san)
        if features.tls_fingerprint:
            add(EvidenceReasonCode.TLS_CERTIFICATE, features.tls_fingerprint)

    # -- HTTP / HTML ----------------------------------------------------------

    def _extract_http(
        self,
        result: ObservationResult,
        features: FeatureSet,
        evidence: list[EvidenceDraft],
        warnings: list[ExtractionWarning],
        source_host: str | None,
    ) -> None:
        http = result.http
        page_url = http.final_url or http.requested_url

        if http.final_hostname:
            features.final_domain = self._normalize_host(
                http.final_hostname, warnings, field="final_hostname"
            )

        if http.redirect_chain:
            features.has_redirect = True
            features.redirect_target_domain = features.final_domain
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.REDIRECT,
                    category=CATEGORY_OF[EvidenceReasonCode.REDIRECT],
                    source_url=http.requested_url,
                    evidence_text=http.final_url,
                    referenced_domain=features.redirect_target_domain,
                    raw_payload={
                        "chain": [hop.model_dump() for hop in http.redirect_chain],
                        "final_url": http.final_url,
                    },
                )
            )

        html = http.html
        if html is None:
            return

        if html.canonical_url:
            features.has_canonical = True
            features.canonical_url = self._safe(
                lambda: norm.normalize_url(html.canonical_url or ""),
                warnings,
                ExtractionWarningCategory.MALFORMED_URL,
                field="canonical_url",
            )
            features.canonical_domain = self._normalize_host(
                html.canonical_url, warnings, field="canonical_url"
            )
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.CANONICAL_URL,
                    category=CATEGORY_OF[EvidenceReasonCode.CANONICAL_URL],
                    source_url=page_url,
                    evidence_text=html.canonical_url,
                    referenced_domain=features.canonical_domain,
                )
            )

        if html.title:
            features.normalized_title = norm.normalize_text(html.title)
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.TITLE,
                    category=CATEGORY_OF[EvidenceReasonCode.TITLE],
                    source_url=page_url,
                    evidence_text=html.title[:_MAX_TEXT],
                    raw_value=html.title[:_MAX_TEXT],
                )
            )

        if html.meta_description:
            features.normalized_meta_description = norm.normalize_text(html.meta_description)
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.META_DESCRIPTION,
                    category=CATEGORY_OF[EvidenceReasonCode.META_DESCRIPTION],
                    source_url=page_url,
                    evidence_text=html.meta_description[:_MAX_TEXT],
                    raw_value=html.meta_description[:_MAX_TEXT],
                )
            )

        if html.content_hash:
            features.content_hash = html.content_hash
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.CONTENT_HASH,
                    category=CATEGORY_OF[EvidenceReasonCode.CONTENT_HASH],
                    source_url=page_url,
                    raw_value=html.content_hash,
                )
            )

        if html.text_excerpt:
            excerpt = html.text_excerpt[:_MAX_TEXT]
            features.normalized_text_excerpt = norm.normalize_text(excerpt)
            features.text_fingerprint = self._safe(
                lambda: norm.text_fingerprint(excerpt),
                warnings,
                ExtractionWarningCategory.INVALID_UNICODE,
                field="text_excerpt",
            )
            features.text_tokens = norm.tokenize(excerpt)
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.CONTENT_TEXT,
                    category=CATEGORY_OF[EvidenceReasonCode.CONTENT_TEXT],
                    source_url=page_url,
                    evidence_text=features.normalized_text_excerpt,
                    raw_payload={
                        "fingerprint": features.text_fingerprint,
                        "token_count": len(features.text_tokens),
                    },
                )
            )

        self._extract_links(
            html.links,
            page_url,
            source_host,
            features.normalized_text_excerpt,
            features,
            evidence,
            warnings,
        )

    def _extract_links(
        self,
        links: list[str],
        page_url: str,
        source_host: str | None,
        normalized_text: str | None,
        features: FeatureSet,
        evidence: list[EvidenceDraft],
        warnings: list[ExtractionWarning],
    ) -> None:
        referenced: dict[str, str] = {}  # host -> first-seen href
        socials: dict[str, SocialProfile] = {}  # normalized url -> profile
        emails: dict[str, str] = {}  # address -> domain
        phones: set[str] = set()

        if len(links) > _MAX_LIST:
            warnings.append(
                ExtractionWarning(
                    category=ExtractionWarningCategory.OVERSIZED_FIELD,
                    detail=f"links truncated from {len(links)} to {_MAX_LIST}",
                    field="links",
                )
            )
        for href in links[:_MAX_LIST]:
            scheme = urlsplit(href).scheme.lower()
            if scheme == "mailto":
                self._collect_email(href[len("mailto:") :].split("?", 1)[0], emails, warnings)
                continue
            if scheme == "tel":
                self._collect_phone(href[len("tel:") :], phones, warnings)
                continue

            absolute = urljoin(page_url, href)
            social = norm.normalize_social_url(absolute)
            try:
                host = norm.host_from_url(absolute)
            except ValueError:
                continue
            if social is not None:
                socials.setdefault(social[1], SocialProfile(platform=social[0], url=social[1]))
                continue
            if source_host is not None and norm.is_same_site(host, source_host):
                continue
            referenced.setdefault(host, href)

        # Emails also appear in plain text; scan the bounded excerpt too.
        if normalized_text:
            for candidate in norm.scan_emails(normalized_text):
                self._collect_email(candidate, emails, warnings)

        self._emit_cross_domain(referenced, page_url, features, evidence)
        self._emit_socials(socials, page_url, features, evidence)
        self._emit_emails(emails, page_url, features, evidence)
        self._emit_phones(phones, page_url, features, evidence)

    # -- DNS ------------------------------------------------------------------

    def _extract_dns(
        self, result: ObservationResult, features: FeatureSet, evidence: list[EvidenceDraft]
    ) -> None:
        buckets: dict[str, list[str]] = {
            "A": features.dns_a,
            "AAAA": features.dns_aaaa,
            "CNAME": features.dns_cname,
            "MX": features.dns_mx,
            "NS": features.dns_ns,
        }
        for record in result.dns.records:
            bucket = buckets.get(record.record_type)
            code = DNS_CODE_BY_RECORD_TYPE.get(record.record_type)
            if bucket is None or code is None or not record.values:
                continue
            values = sorted(record.values)[:_MAX_LIST]
            bucket.extend(values)
            evidence.append(
                EvidenceDraft(
                    reason_code=code,
                    category=CATEGORY_OF[code],
                    evidence_text=", ".join(values)[:_MAX_TEXT],
                    raw_payload={"values": values},
                )
            )

    # -- emit helpers ---------------------------------------------------------

    def _emit_cross_domain(
        self,
        referenced: dict[str, str],
        page_url: str,
        features: FeatureSet,
        evidence: list[EvidenceDraft],
    ) -> None:
        for host, href in sorted(referenced.items()):
            features.referenced_domains.append(host)
            features.cross_domain_references.append(
                CrossDomainReference(
                    referenced_domain=host, source_url=page_url, evidence_text=href
                )
            )
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.CROSS_DOMAIN_REFERENCE,
                    category=CATEGORY_OF[EvidenceReasonCode.CROSS_DOMAIN_REFERENCE],
                    source_url=page_url,
                    evidence_text=href,
                    referenced_domain=host,
                )
            )

    def _emit_socials(
        self,
        socials: dict[str, SocialProfile],
        page_url: str,
        features: FeatureSet,
        evidence: list[EvidenceDraft],
    ) -> None:
        for url in sorted(socials):
            profile = socials[url]
            features.social_profiles.append(profile)
            host = norm.host_from_url(url)
            if host not in features.social_domains:
                features.social_domains.append(host)
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.SOCIAL_PROFILE,
                    category=CATEGORY_OF[EvidenceReasonCode.SOCIAL_PROFILE],
                    source_url=page_url,
                    evidence_text=url,
                    raw_payload={"platform": profile.platform},
                )
            )

    def _emit_emails(
        self,
        emails: dict[str, str],
        page_url: str | None,
        features: FeatureSet,
        evidence: list[EvidenceDraft],
    ) -> None:
        for address in sorted(emails):
            domain = emails[address]
            features.email_addresses.append(address)
            if domain not in features.email_domains:
                features.email_domains.append(domain)
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.EMAIL_DOMAIN,
                    category=CATEGORY_OF[EvidenceReasonCode.EMAIL_DOMAIN],
                    source_url=page_url,
                    evidence_text=address,
                    referenced_domain=domain,
                    raw_value=domain,
                )
            )

    def _emit_phones(
        self,
        phones: set[str],
        page_url: str,
        features: FeatureSet,
        evidence: list[EvidenceDraft],
    ) -> None:
        for phone in sorted(phones):
            features.phone_numbers.append(phone)
            evidence.append(
                EvidenceDraft(
                    reason_code=EvidenceReasonCode.PHONE,
                    category=CATEGORY_OF[EvidenceReasonCode.PHONE],
                    source_url=page_url,
                    raw_value=phone,
                )
            )

    # -- primitives -----------------------------------------------------------

    def _collect_email(
        self, candidate: str, emails: dict[str, str], warnings: list[ExtractionWarning]
    ) -> None:
        try:
            local, domain = norm.normalize_email(candidate)
        except ValueError:
            warnings.append(
                ExtractionWarning(
                    category=ExtractionWarningCategory.INVALID_EMAIL,
                    detail=f"invalid email {candidate!r}",
                    field="email",
                )
            )
            return
        emails[f"{local}@{domain}"] = domain

    def _collect_phone(
        self, candidate: str, phones: set[str], warnings: list[ExtractionWarning]
    ) -> None:
        try:
            phones.add(norm.normalize_phone(candidate))
        except ValueError:
            warnings.append(
                ExtractionWarning(
                    category=ExtractionWarningCategory.INVALID_PHONE,
                    detail=f"invalid phone {candidate!r}",
                    field="phone",
                )
            )

    def _normalize_host(
        self, value: str, warnings: list[ExtractionWarning], *, field: str
    ) -> str | None:
        try:
            if "//" in value or "/" in value:
                return norm.host_from_url(value)
            return norm.normalize_domain_value(value)
        except ValueError:
            warnings.append(
                ExtractionWarning(
                    category=ExtractionWarningCategory.MALFORMED_URL,
                    detail=f"could not normalize host from {value!r}",
                    field=field,
                )
            )
            return None

    def _safe(
        self,
        fn: Callable[[], str],
        warnings: list[ExtractionWarning],
        category: ExtractionWarningCategory,
        *,
        field: str,
    ) -> str | None:
        try:
            return fn()
        except (ValueError, UnicodeError) as exc:
            warnings.append(ExtractionWarning(category=category, detail=str(exc), field=field))
            return None
