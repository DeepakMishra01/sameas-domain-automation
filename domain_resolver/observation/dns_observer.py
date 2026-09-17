"""Factual DNS observation.

Collects A/AAAA/CNAME/MX/NS records where available. DNS data is recorded as
fact only: DNS similarity is never treated as proof of ownership, and DNS
failures never raise out of the observer — they are captured as structured
error information so one domain's failure cannot crash an observation job.
"""

from __future__ import annotations

import dns.exception
import dns.rdatatype
import dns.resolver

from domain_resolver.models.entities import ObservationErrorCategory
from domain_resolver.observation.limits import DEFAULT_LIMITS, ObservationLimits
from domain_resolver.observation.results import DnsObservation, DnsRecordSet

_RECORD_TYPES: tuple[str, ...] = ("A", "AAAA", "CNAME", "MX", "NS")


class DnsObserver:
    """Resolve a bounded set of record types for a hostname."""

    def __init__(self, limits: ObservationLimits = DEFAULT_LIMITS) -> None:
        self._limits = limits

    def observe(self, hostname: str) -> DnsObservation:
        resolver = dns.resolver.Resolver()
        resolver.timeout = self._limits.dns_timeout
        resolver.lifetime = self._limits.dns_lifetime

        records: list[DnsRecordSet] = []
        error_category: ObservationErrorCategory | None = None
        error_detail: str | None = None

        for record_type in _RECORD_TYPES:
            record_set = self._resolve(resolver, hostname, record_type)
            records.append(record_set)
            # NXDOMAIN is a property of the name, not a single record type: surface
            # it once as the observation-level error without failing the run.
            if record_set.error == "NXDOMAIN" and error_category is None:
                error_category = ObservationErrorCategory.DNS_ERROR
                error_detail = "NXDOMAIN"

        return DnsObservation(
            hostname=hostname,
            records=records,
            error_category=error_category,
            error_detail=error_detail,
        )

    def _resolve(
        self, resolver: dns.resolver.Resolver, hostname: str, record_type: str
    ) -> DnsRecordSet:
        try:
            answer = resolver.resolve(hostname, record_type, raise_on_no_answer=True)
        except dns.resolver.NXDOMAIN:
            return DnsRecordSet(record_type=record_type, error="NXDOMAIN")
        except dns.resolver.NoAnswer:
            return DnsRecordSet(record_type=record_type)
        except dns.resolver.NoNameservers:
            return DnsRecordSet(record_type=record_type, error="NO_NAMESERVERS")
        except dns.exception.Timeout:
            return DnsRecordSet(record_type=record_type, error="TIMEOUT")
        except dns.exception.DNSException as exc:
            return DnsRecordSet(record_type=record_type, error=f"{type(exc).__name__}")

        values = sorted(rdata.to_text() for rdata in answer)
        return DnsRecordSet(record_type=record_type, values=values)
