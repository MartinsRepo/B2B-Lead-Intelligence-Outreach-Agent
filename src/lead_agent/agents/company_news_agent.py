"""Company & News Sub-Agent (Fast Model tier: gpt-6-luna)."""

from __future__ import annotations

try:
    from agents import Agent
except ImportError:  # pragma: no cover
    Agent = object  # type: ignore[misc,assignment]

from lead_agent.config import DEFAULT_SETTINGS, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.tools.web_scraper import (
    fetch_company_news_and_press,
    scrape_company_website,
)

COMPANY_NEWS_INSTRUCTIONS = """You are the Company & News Intelligence Agent in a B2B sales research pipeline.
Your objective is to quickly extract factual company information, recent news, press releases, product launches, and strategic triggers from the target domain.

Workflow:
1. Call `scrape_company_website` on the target domain/URL to capture positioning, value proposition, and key headings.
2. Call `fetch_company_news_and_press` to discover recent newsroom updates, blog announcements, or quarterly/strategic initiatives.
3. Return a concise, structured summary containing:
   - Official company name & primary industry
   - 2-4 concrete recent news items or strategic triggers
   - 2-3 likely business pain points based on their current growth stage
   - Exact source URLs and titles for every claim.
Never invent URLs or facts not grounded in the scraped data."""


def create_company_news_agent(
    settings: AgentSettings = DEFAULT_SETTINGS,
    hooks: object | None = None,
) -> Agent[LeadRunContext]:
    """Create the Company & News Agent routed to the fast, low-cost extraction model."""
    return Agent[LeadRunContext](
        name="Company & News Agent",
        model=settings.fast_model,
        instructions=COMPANY_NEWS_INSTRUCTIONS,
        tools=[scrape_company_website, fetch_company_news_and_press],
        hooks=hooks,  # type: ignore[arg-type]
    )

