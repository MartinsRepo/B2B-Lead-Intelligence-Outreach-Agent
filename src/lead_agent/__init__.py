"""B2B Lead Intelligence & Outreach Agent package."""

from lead_agent.agents import (
    create_company_news_agent,
    create_copywriter_agent,
    create_lead_orchestrator,
    create_tech_stack_agent,
    run_lead_intelligence_pipeline,
)
from lead_agent.config import DEFAULT_SETTINGS, AgentSettings, ModelPricing
from lead_agent.context import AgentUsageRecord, LeadRunContext
from lead_agent.fact_checker import (
    extract_best_matching_passage,
    verify_and_ground_lead_report,
)
from lead_agent.guardrails import (
    ValidationOutcome,
    validate_lead_input,
    validate_lead_output,
)
from lead_agent.schemas import (
    DetectedTechnology,
    LeadReport,
    OutreachPitch,
    SourceCitation,
    TechStackAnalysis,
    VerifiedClaim,
)
from lead_agent.security import (
    SSRFBlockedError,
    SSRFCheckOutcome,
    build_ip_pinned_url_and_headers,
    filter_safe_external_urls,
    is_ip_blocked,
    safe_http_get,
    validate_url_ssrf,
)

__all__ = [
    "AgentSettings",
    "AgentUsageRecord",
    "DEFAULT_SETTINGS",
    "DetectedTechnology",
    "LeadReport",
    "LeadRunContext",
    "ModelPricing",
    "OutreachPitch",
    "SSRFBlockedError",
    "SSRFCheckOutcome",
    "SourceCitation",
    "TechStackAnalysis",
    "ValidationOutcome",
    "VerifiedClaim",
    "build_ip_pinned_url_and_headers",
    "create_company_news_agent",
    "create_copywriter_agent",
    "create_lead_orchestrator",
    "create_tech_stack_agent",
    "extract_best_matching_passage",
    "filter_safe_external_urls",
    "is_ip_blocked",
    "run_lead_intelligence_pipeline",
    "safe_http_get",
    "validate_lead_input",
    "validate_lead_output",
    "validate_url_ssrf",
    "verify_and_ground_lead_report",
]
