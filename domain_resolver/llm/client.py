"""Model-agnostic LLM client (Ollama by default, Gemini optional).

No paid dependency by default: Ollama runs locally and free. Gemini is available
by setting ``DERE_LLM_PROVIDER=gemini`` and ``DERE_GEMINI_API_KEY``. Both talk over
plain HTTP via httpx (already a project dependency), so no new packages are added.

Environment:
  DERE_LLM_PROVIDER   ollama | gemini            (default: ollama)
  DERE_LLM_MODEL      e.g. qwen2.5:14b-instruct  (sensible default per provider)
  DERE_OLLAMA_URL     default http://localhost:11434
  DERE_GEMINI_API_KEY required only for gemini
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class LlmClient(Protocol):
    """Minimal chat interface: system + user prompt -> raw model text."""

    @property
    def model(self) -> str: ...

    def complete(self, system: str, user: str) -> str: ...


class OllamaClient:
    """Local Ollama chat client (free, private). Requests strict JSON output."""

    def __init__(
        self, model: str, base_url: str = "http://localhost:11434", timeout: float = 120.0
    ) -> None:
        self._model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system: str, user: str) -> str:
        response = httpx.post(
            f"{self._base}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return str(response.json()["message"]["content"])


class GeminiClient:
    """Google Gemini REST client (paid; cheap Flash tier). Requests JSON output."""

    def __init__(self, model: str, api_key: str, timeout: float = 60.0) -> None:
        self._model = model
        self._key = api_key
        self._timeout = timeout

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system: str, user: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._key}"
        )
        response = httpx.post(
            url,
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        candidates = response.json()["candidates"]
        return str(candidates[0]["content"]["parts"][0]["text"])


def build_client_from_env() -> LlmClient:
    """Construct the configured client from environment variables."""
    provider = os.environ.get("DERE_LLM_PROVIDER", "ollama").lower()
    if provider == "ollama":
        model = os.environ.get("DERE_LLM_MODEL", "qwen2.5:14b-instruct")
        return OllamaClient(model, os.environ.get("DERE_OLLAMA_URL", "http://localhost:11434"))
    if provider == "gemini":
        key = os.environ.get("DERE_GEMINI_API_KEY", "")
        if not key:
            raise RuntimeError("DERE_GEMINI_API_KEY is required for the gemini provider")
        model = os.environ.get("DERE_LLM_MODEL", "gemini-1.5-flash")
        return GeminiClient(model, key)
    raise RuntimeError(f"unknown DERE_LLM_PROVIDER {provider!r} (use 'ollama' or 'gemini')")
