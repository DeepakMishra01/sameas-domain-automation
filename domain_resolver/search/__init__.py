"""Optional web-search evidence (Serper / Google) for low-confidence pairs.

When the LLM is unsure (confidence below a threshold), we fetch Google results
for the two domains via Serper and feed the snippets back to the LLM so it can
decide with external knowledge (acquisitions, ownership, "part of") that the two
pages alone do not reveal. Cheap, and only the uncertain subset triggers it.
"""

from domain_resolver.search.serper import SerperClient, build_serper_from_env

__all__ = ["SerperClient", "build_serper_from_env"]
