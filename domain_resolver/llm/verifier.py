"""LLM relationship verifier: turns a model completion into a typed AiVerdict.

Robust by design: any client error, malformed JSON, or unknown category yields
``None`` so the caller keeps the deterministic result. The LLM never silently
breaks the pipeline.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from domain_resolver.classification.relationship_types import PartOfSubtype, RelationshipType
from domain_resolver.llm.client import LlmClient
from domain_resolver.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from domain_resolver.llm.results import AiVerdict
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


def _coerce_type(value: Any) -> RelationshipType | None:
    try:
        return RelationshipType(str(value).strip().upper())
    except ValueError:
        return None


def _coerce_subtype(value: Any) -> PartOfSubtype | None:
    if value is None:
        return None
    try:
        return PartOfSubtype(str(value).strip().upper())
    except ValueError:
        return None


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _coerce_bool(value: Any) -> bool | None:
    """Parse a tri-state boolean from the model (true / false / unknown)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "same", "1"}:
        return True
    if text in {"false", "no", "different", "0"}:
        return False
    return None


class LlmRelationshipVerifier:
    def __init__(self, client: LlmClient) -> None:
        self._client = client

    def verify(
        self,
        view_a: DomainFeatureView,
        view_b: DomainFeatureView,
        deterministic_hint: str = "",
        web_evidence: str = "",
        domain_a_sector: str = "",
    ) -> AiVerdict | None:
        try:
            raw = self._client.complete(
                SYSTEM_PROMPT,
                build_user_prompt(
                    view_a, view_b, deterministic_hint, web_evidence, domain_a_sector
                ),
            )
        except Exception as exc:  # noqa: BLE001 - any transport error -> keep deterministic
            if os.environ.get("DERE_LLM_DEBUG"):
                print(f"[llm] {type(exc).__name__}: {exc}", file=sys.stderr)
            return None

        data = _extract_json(raw)
        if data is None:
            return None
        rel_type = _coerce_type(data.get("relationship_type"))
        if rel_type is None:
            return None

        return AiVerdict(
            relationship_type=rel_type,
            relationship_subtype=_coerce_subtype(data.get("relationship_subtype")),
            primary_domain=_clean_host(data.get("primary_domain")),
            secondary_domain=_clean_host(data.get("secondary_domain")),
            evidence_quote=str(data.get("evidence_quote") or "")[:500],
            reasoning=str(data.get("reasoning") or "")[:500],
            confidence=_coerce_confidence(data.get("confidence")),
            model=self._client.model,
            same_sector=_coerce_bool(data.get("same_sector")),
        )


def _clean_host(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    return text or None
