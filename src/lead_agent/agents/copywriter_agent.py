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
Given the findings from the Company & News Agent and the Tech-Stack Agent, craft a high-converting B2B outreach and phone call brief package.

You must produce:
1. `subject_line`: Specific, curiosity-inducing subject line referencing a real company initiative or tech stack signal (no clickbait).
2. `hyper_personalized_pitch`: A sharp, executive-ready cold outreach message (100-160 words) that weaves together:
   - A specific recent news item or press trigger
   - Specific technologies or hiring signals detected in their stack
   - A clear hypothesis of their core engineering/business pain point
3. `icebreaker_hook`: A 1-2 sentence direct message / short-form icebreaker (<280 chars).
4. `call_to_action`: A low-friction, value-first CTA (e.g., sharing a benchmark or 10-minute architecture teardown).
5. `phone_call_bullet_points`: 4-5 ultra-concise, scannable memory notices (bullet points) for a sales rep making a short phone call:
   - **Opening Trigger:** The exact recent news or launch to reference in the first 10 seconds
   - **Tech & Hiring Signal:** Key confirmed/suspected stack technologies and open roles to mention
   - **Pain-Point Hypothesis:** The primary bottleneck they are likely facing right now
   - **Discovery Question:** A sharp, open-ended question to ask the prospect on the call
   - **Next-Step Close:** The low-friction follow-up offer."""


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
