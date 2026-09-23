"""Unit tests for LLM client selection from environment (no network)."""

import pytest

from domain_resolver.llm.client import (
    OllamaClient,
    OpenAICompatibleClient,
    build_client_from_env,
)


def test_default_provider_is_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DERE_LLM_PROVIDER", raising=False)
    assert isinstance(build_client_from_env(), OllamaClient)


def test_nvidia_provider_uses_openai_compatible_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DERE_LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("DERE_NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("DERE_LLM_MODEL", "meta/llama-3.3-70b-instruct")
    client = build_client_from_env()
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model == "meta/llama-3.3-70b-instruct"


def test_nvidia_provider_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DERE_LLM_PROVIDER", "nvidia")
    monkeypatch.delenv("DERE_NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("DERE_LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        build_client_from_env()


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DERE_LLM_PROVIDER", "banana")
    with pytest.raises(RuntimeError):
        build_client_from_env()
