"""LLM geo verifier: turns a model completion into a typed GeoVerdict.

Robust by design: any client error, malformed JSON, or missing fields yields
``None`` so the caller can record "needs review" instead of crashing.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from domain_resolver.geo.prompt import SYSTEM_PROMPT, build_user_prompt
from domain_resolver.geo.results import GeoVerdict
from domain_resolver.llm.client import LlmClient
from domain_resolver.matching.views import DomainFeatureView


def _extract_json(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _coerce_countries(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


class GeoVerifier:
    def __init__(self, client: LlmClient) -> None:
        self._client = client

    def verify(
        self, view: DomainFeatureView, company_name: str = "", web_evidence: str = ""
    ) -> GeoVerdict | None:
        try:
            raw = self._client.complete(
                SYSTEM_PROMPT, build_user_prompt(view, company_name, web_evidence)
            )
        except Exception as exc:  # noqa: BLE001 - any transport error -> needs review
            if os.environ.get("DERE_LLM_DEBUG"):
                print(f"[geo-llm] {type(exc).__name__}: {exc}", file=sys.stderr)
            return None

        data = _extract_json(raw)
        if data is None:
            return None
        hq = data.get("headquarters")
        return GeoVerdict(
            countries=_coerce_countries(data.get("countries")),
            headquarters=(str(hq).strip() or None) if hq else None,
            evidence_quote=str(data.get("evidence_quote") or "")[:500],
            reasoning=str(data.get("reasoning") or "")[:500],
            confidence=_coerce_confidence(data.get("confidence")),
            model=self._client.model,
        )
