"""Optional LLM layer: reasoned verification of the uncertain relationship pairs.

Deterministic, evidence-backed classifications stay authoritative; this layer runs
only on the assumed/low-confidence/review pairs, reading already-stored page facts
(no re-crawl) via a local Ollama model by default (free, private) or Gemini.
"""

from domain_resolver.llm.client import LlmClient, build_client_from_env
from domain_resolver.llm.results import AiVerdict
from domain_resolver.llm.verifier import LlmRelationshipVerifier

__all__ = ["AiVerdict", "LlmClient", "LlmRelationshipVerifier", "build_client_from_env"]
