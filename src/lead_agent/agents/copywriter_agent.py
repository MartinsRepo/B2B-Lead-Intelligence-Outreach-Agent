"""Outreach Copywriter Sub-Agent (Reasoning Model tier: gpt-6.2-sol)."""

from __future__ import annotations

try:
    from agents import Agent
except ImportError:  # pragma: no cover
    Agent = object  # type: ignore[misc,assignment]

from lead_agent.config import DEFAULT_SETTINGS, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.schemas import OutreachPitch

COPYWRITER_INSTRUCTIONS = """You are an elite B2B Executive Copywriter Agent powered by a high-reasoning model.
Given the findings from the Company & News Agent and the Tech-Stack Agent, craft a high-converting B2B outreach package.

You must produce:
1. `subject_line`: Specific, curiosity-inducing subject line referencing a real company initiative or tech stack signal (no clickbait).
2. `generic_ai_message` ("Before"): A realistic example of a mediocre, generic AI cold email ("I hope this email finds you well, I saw your company is doing great things in [industry]...") so the user can showcase a stark Before vs. After comparison on LinkedIn.
3. `hyper_personalized_pitch` ("After"): A sharp, executive-ready cold outreach message (100-160 words) that weaves together:
   - A specific recent news item or press trigger
   - Specific technologies or hiring signals detected in their stack
   - A clear hypothesis of their core engineering/business pain point
4. `icebreaker_hook`: A 1-2 sentence LinkedIn connection note (<280 chars).
5. `call_to_action`: A low-friction, value-first CTA (e.g., sharing a benchmark or 10-minute architecture teardown)."""


def create_copywriter_agent(
    settings: AgentSettings = DEFAULT_SETTINGS,
    hooks: object | None = None,
) -> Agent[LeadRunContext]:
    """Create the Outreach Copywriter Agent routed to the stronger reasoning model."""
    return Agent[LeadRunContext](
        name="Outreach Copywriter Agent",
        model=settings.reasoning_model,
        instructions=COPYWRITER_INSTRUCTIONS,
        output_type=OutreachPitch,
        hooks=hooks,  # type: ignore[arg-type]
    )

