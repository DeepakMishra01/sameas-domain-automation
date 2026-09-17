import pytest

from domain_resolver.config.settings import Settings


def test_database_configuration_loads() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://user:pass@db:5432/dere")
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.model_version == "dere-v1"


def test_database_url_is_not_required_for_liveness_configuration() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url is None
    with pytest.raises(RuntimeError, match="DERE_DATABASE_URL"):
        settings.require_database_url()
