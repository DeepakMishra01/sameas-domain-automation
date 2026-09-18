"""FastAPI dependency providers."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from domain_resolver.config.settings import Settings, get_settings
from domain_resolver.features.extractor import FeatureExtractor
from domain_resolver.infrastructure.database import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)
from domain_resolver.matching.config import MatcherConfig
from domain_resolver.matching.matcher import OrganizationMatcher
from domain_resolver.observation.dns_observer import DnsObserver
from domain_resolver.observation.http_observer import HttpObserver
from domain_resolver.observation.service import DnsObserverPort, HttpObserverPort
from domain_resolver.resolution.config import ResolverConfig
from domain_resolver.resolution.resolver import PrimaryDomainResolver


async def settings_dependency() -> Settings:
    """Return immutable process configuration for request handlers."""
    return get_settings()


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    """Build the process-wide session factory lazily from settings.

    Only invoked by database-backed routes, so importing the app and serving the
    health endpoint never requires a configured database.
    """
    return create_session_factory(create_engine_from_settings(get_settings()))


def session_dependency() -> Generator[Session, None, None]:
    """Yield a request-scoped session inside an explicit transaction."""
    with session_scope(_session_factory()) as session:
        yield session


def dns_observer_dependency() -> DnsObserverPort:
    """Provide the production DNS observer (overridable in tests)."""
    return DnsObserver()


def http_observer_dependency() -> HttpObserverPort:
    """Provide the production, SSRF-safe HTTP observer (overridable in tests)."""
    return HttpObserver()


def feature_extractor_dependency() -> FeatureExtractor:
    """Provide the deterministic feature extractor at the configured version."""
    return FeatureExtractor(get_settings().feature_extractor_version)


def organization_matcher_dependency() -> OrganizationMatcher:
    """Provide the deterministic organization matcher at the configured version."""
    return OrganizationMatcher(MatcherConfig(version=get_settings().matcher_version))


def primary_resolver_dependency() -> PrimaryDomainResolver:
    """Provide the deterministic primary-domain resolver at the configured version."""
    return PrimaryDomainResolver(ResolverConfig(version=get_settings().resolver_version))
