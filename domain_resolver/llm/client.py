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
import random
import time
from typing import Protocol, runtime_checkable

import httpx

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 5
_BASE_BACKOFF = 2.0
_MAX_BACKOFF = 30.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse a Retry-After header (seconds form) if the server sent one."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds: float = float(value)
    except ValueError:
        return None
    return max(0.0, seconds)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff (2, 4, 8, 16 … capped) plus jitter to de-sync workers."""
    return float(min(_MAX_BACKOFF, _BASE_BACKOFF * (2**attempt)) + random.uniform(0.0, 1.0))


def _post_with_retry(
    url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float
) -> httpx.Response:
    """POST with retries on transient (429/5xx/transport) errors.

    Uses exponential backoff with jitter and honours a ``Retry-After`` header, so
    concurrent workers hitting a rate limit back off (and de-synchronise) instead
    of hammering the API. Jitter is what stops many parallel workers from retrying
    in lockstep and re-tripping the limit.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = httpx.post(url, headers=headers, json=json, timeout=timeout)
            if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
                delay = _retry_after_seconds(response)
                time.sleep(delay if delay is not None else _backoff_delay(attempt))
                continue
            response.raise_for_status()
            return response
        except httpx.TransportError as exc:  # network blip / read timeout
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_backoff_delay(attempt))
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("request failed after retries")


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


class OpenAICompatibleClient:
    """OpenAI chat-completions API client — works with NVIDIA NIM, OpenAI, etc.

    NVIDIA's build.nvidia.com endpoint serves large open models (Llama 3.3 70B,
    Qwen 2.5 72B, …) on their GPUs via this exact format, so the same client
    covers it by pointing ``base_url`` at the NVIDIA endpoint.
    """

    def __init__(self, model: str, base_url: str, api_key: str, timeout: float = 90.0) -> None:
        self._model = model
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system: str, user: str) -> str:
        response = _post_with_retry(
            f"{self._base}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            },
            timeout=self._timeout,
        )
        choices = response.json()["choices"]
        return str(choices[0]["message"]["content"])


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
    if provider == "nvidia":
        key = os.environ.get("DERE_NVIDIA_API_KEY") or os.environ.get("DERE_LLM_API_KEY", "")
        if not key:
            raise RuntimeError("DERE_NVIDIA_API_KEY is required for the nvidia provider")
        model = os.environ.get("DERE_LLM_MODEL", "meta/llama-3.3-70b-instruct")
        base = os.environ.get("DERE_LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        return OpenAICompatibleClient(model, base, key)
    if provider == "openai":
        key = os.environ.get("DERE_LLM_API_KEY", "")
        if not key:
            raise RuntimeError("DERE_LLM_API_KEY is required for the openai provider")
        model = os.environ.get("DERE_LLM_MODEL", "gpt-4o-mini")
        base = os.environ.get("DERE_LLM_BASE_URL", "https://api.openai.com/v1")
        return OpenAICompatibleClient(model, base, key)
    raise RuntimeError(
        f"unknown DERE_LLM_PROVIDER {provider!r} (use 'ollama', 'gemini', 'nvidia', or 'openai')"
    )
