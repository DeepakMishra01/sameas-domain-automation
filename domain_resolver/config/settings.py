"""Typed runtime configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Non-secret application settings; database credentials are environment supplied."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DERE_", extra="ignore")

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    model_version: str = Field(default="dere-v1")
    database_url: str | None = Field(default=None, repr=False)
    test_database_url: str | None = Field(default=None, repr=False)

    # Identifies which collector produced a stored observation. Defined once here
    # so historical observations remain attributable to a specific collector.
    collector_version: str = Field(default="domain-observer-v2")

    # Identifies which deterministic feature extractor produced a feature snapshot
    # and its evidence, so historical feature versions stay attributable and can
    # coexist. Defined once here (Phase 4).
    feature_extractor_version: str = Field(default="feature-extractor-v2")

    # Identifies which deterministic organization matcher produced a relationship
    # assessment, so versions coexist and can be evaluated against CPT data
    # (Phase 5). The matcher's weights/thresholds are persisted per version.
    matcher_version: str = Field(default="org-matcher-v1")

    # Identifies which deterministic primary-domain resolver produced a resolution
    # (Phase 6), so versions coexist and can be tuned against CPT data.
    resolver_version: str = Field(default="primary-v1")

    # Celery broker/result backend for the optional asynchronous worker. Never a
    # secret is logged from here; the values are provided by the environment.
    celery_broker_url: str = Field(default="redis://localhost:6379/0", repr=False)
    celery_result_backend: str = Field(default="redis://localhost:6379/1", repr=False)

    def require_database_url(self) -> str:
        """Return the configured production database URL or fail at use time."""
        if self.database_url is None:
            raise RuntimeError("DERE_DATABASE_URL must be configured before using the database")
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""
    return Settings()
