"""Serper.dev Google Search client (used only for low-confidence verification).

Returns a compact, text block of the top organic results and any knowledge-graph
entry, suitable to paste into the LLM prompt as extra evidence. Dependency-free
(httpx). Any error returns an empty string so the pipeline degrades gracefully.
"""

from __future__ import annotations

import os

import httpx

_ENDPOINT = "https://google.serper.dev/search"


class SerperClient:
    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._key = api_key
        self._timeout = timeout

    def search(self, query: str, num: int = 6) -> str:
        """Return a text block of Google results for ``query`` (or "" on failure)."""
        try:
            response = httpx.post(
                _ENDPOINT,
                headers={"X-API-KEY": self._key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:  # noqa: BLE001 - search is best-effort; never break the pipeline
            return ""
        return self._format(data, num)

    @staticmethod
    def _format(data: dict[str, object], num: int) -> str:
        lines: list[str] = []
        kg = data.get("knowledgeGraph")
        if isinstance(kg, dict):
            title = str(kg.get("title", "")).strip()
            desc = str(kg.get("description", "")).strip()
            typ = str(kg.get("type", "")).strip()
            if title:
                lines.append(f"knowledge_graph: {title} ({typ}) - {desc}".strip(" -"))
        organic = data.get("organic")
        if isinstance(organic, list):
            for item in organic[:num]:
                if isinstance(item, dict):
                    title = str(item.get("title", "")).strip()
                    snippet = str(item.get("snippet", "")).strip()
                    if title or snippet:
                        lines.append(f"- {title}: {snippet}")
        return "\n".join(lines)


def build_serper_from_env() -> SerperClient | None:
    """Return a SerperClient if DERE_SERPER_API_KEY is set, else None (feature off)."""
    key = os.environ.get("DERE_SERPER_API_KEY", "")
    return SerperClient(key) if key else None
