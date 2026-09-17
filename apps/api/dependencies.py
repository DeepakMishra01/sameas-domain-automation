"""FastAPI dependency providers."""

from domain_resolver.config.settings import Settings, get_settings


async def settings_dependency() -> Settings:
    """Return immutable process configuration for request handlers."""
    return get_settings()
