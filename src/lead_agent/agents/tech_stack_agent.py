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

TECH_STACK_INSTRUCTIONS = """You are the Evidence-Based Tech-Stack & Engineering Signals Agent in a B2B lead intelligence pipeline.
Your objective is to uncover the target company's technology stack and engineering priorities while avoiding false positives.

Workflow:
1. Call `detect_website_tech_stack` on the target domain to identify confirmed runtime technologies (from HTTP headers, script assets, DOM attributes, and meta generators) versus suspected text mentions.
2. Call `scrape_careers_and_job_postings` to scan their careers/jobs page for backend languages, data infrastructure, AI/ML initiatives, and open engineering roles.
3. For every technology found, preserve its structured evidence in `technology_signals`:
   - `name`: Technology name
   - `confidence_score`: Numeric score from 0.0 to 1.0
   - `signal_source`: Exact source (e.g., `http_header`, `script_asset`, `meta_generator`, `job_posting_requirement`, or `body_text_mention`)
   - `detected_at`: ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`)
   - `detection_status`: `'confirmed'` (confidence >= 0.80, direct runtime proof) vs. `'suspected'` (confidence < 0.80, inferred from job postings or text mentions)
4. Also return:
   - `detected_technologies`: Summary list of technology names
   - `hiring_signals`: Key open engineering/product roles and demanded skills
   - `inferred_infrastructure_needs`: Synthesis of technical bottlenecks."""


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
