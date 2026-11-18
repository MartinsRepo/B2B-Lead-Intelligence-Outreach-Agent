"""Tech-Stack & Job-Board Sub-Agent (Fast Model tier: gpt-6-luna)."""

from __future__ import annotations

try:
    from agents import Agent
except ImportError:  # pragma: no cover
    Agent = object  # type: ignore[misc,assignment]

from lead_agent.config import DEFAULT_SETTINGS, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.tools.tech_parser import (
    detect_website_tech_stack,
    scrape_careers_and_job_postings,
)

TECH_STACK_INSTRUCTIONS = """You are the Tech-Stack & Engineering Signals Agent in a B2B lead intelligence pipeline.
Your objective is to uncover the target company's technology stack and engineering priorities.

Workflow:
1. Call `detect_website_tech_stack` on the target domain to identify frontend frameworks, cloud/CDN providers, analytics, and CRM integrations.
2. Call `scrape_careers_and_job_postings` to scan their careers/jobs page for backend languages, data infrastructure, AI/ML initiatives, and open engineering roles.
3. Synthesize:
   - Detected technologies (frontend, backend, cloud, data, GTM tools)
   - Hiring signals (key open engineering/product roles and demanded skills)
   - Inferred infrastructure needs or technical bottlenecks
   - Exact URLs inspected."""


def create_tech_stack_agent(
    settings: AgentSettings = DEFAULT_SETTINGS,
    hooks: object | None = None,
) -> Agent[LeadRunContext]:
    """Create the Tech-Stack Agent routed to the fast, low-cost extraction model."""
    return Agent[LeadRunContext](
        name="Tech-Stack Agent",
        model=settings.fast_model,
        instructions=TECH_STACK_INSTRUCTIONS,
        tools=[detect_website_tech_stack, scrape_careers_and_job_postings],
        hooks=hooks,  # type: ignore[arg-type]
    )

