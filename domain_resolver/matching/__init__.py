"""Phase 5 organization matching.

Answers only "do these domains belong to the same organization?" from
already-collected Phase 4 features and evidence. It is deterministic and
explainable, and does NOT select a primary domain, produce a final CPT decision,
call an LLM, use embeddings/ML, or make any network call.
"""

from domain_resolver.matching.config import (
    DEFAULT_MATCHER_CONFIG,
    MATCHER_VERSION,
    MatcherConfig,
)
from domain_resolver.matching.evaluation import EvaluationReport, evaluate
from domain_resolver.matching.grouping import OrganizationGroup, group_domains
from domain_resolver.matching.matcher import ConfidenceBand, MatchResult, OrganizationMatcher
from domain_resolver.matching.reason_codes import MatchReasonCode
from domain_resolver.matching.service import (
    MatchingReport,
    run_matching,
    run_organization_matching,
)
from domain_resolver.matching.views import DomainFeatureView

__all__ = [
    "DEFAULT_MATCHER_CONFIG",
    "MATCHER_VERSION",
    "ConfidenceBand",
    "DomainFeatureView",
    "EvaluationReport",
    "MatchReasonCode",
    "MatchResult",
    "MatcherConfig",
    "MatchingReport",
    "OrganizationGroup",
    "OrganizationMatcher",
    "evaluate",
    "group_domains",
    "run_matching",
    "run_organization_matching",
]
