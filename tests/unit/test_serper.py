"""Unit tests for the Serper search client (no network) and env selection."""

import pytest

from domain_resolver.search.serper import SerperClient, build_serper_from_env


def test_format_includes_knowledge_graph_and_organic() -> None:
    data = {
        "knowledgeGraph": {
            "title": "Boris FX",
            "type": "Software company",
            "description": "Boris FX is a developer of visual effects software.",
        },
        "organic": [
            {
                "title": "Boris FX acquires Samplitude",
                "snippet": "Boris FX announced it acquired...",
            },
            {"title": "Samplitude | Boris FX", "snippet": "Samplitude is now part of Boris FX."},
        ],
    }
    text = SerperClient._format(data, 6)
    assert "knowledge_graph: Boris FX" in text
    assert "acquires Samplitude" in text
    assert "now part of Boris FX" in text


def test_format_handles_empty() -> None:
    assert SerperClient._format({}, 6) == ""


def test_build_serper_from_env_off_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DERE_SERPER_API_KEY", raising=False)
    assert build_serper_from_env() is None


def test_build_serper_from_env_on_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DERE_SERPER_API_KEY", "test-key")
    client = build_serper_from_env()
    assert isinstance(client, SerperClient)
