"""Pydantic v2 structured output schemas for the B2B Lead Intelligence & Outreach Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SourceCitation(BaseModel):
    """Verified external source citation grounding the lead intelligence report."""

    title: str = Field(
        description="Title or clear description of the cited webpage, job posting, or article."
    )
    url: str = Field(
        description="Full HTTP/HTTPS URL of the source (press release, company page, job board)."
    )
    snippet: str = Field(
        description="Concise factual quote or takeaway extracted from this source."
    )

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            raise ValueError(f"Source URL must start with http:// or https://, got: {cleaned}")
        return cleaned


class TechStackAnalysis(BaseModel):
    """Technical footprint and engineering hiring intelligence."""

    detected_technologies: list[str] = Field(
        default_factory=list,
        description="Frontend, backend, cloud, analytics, and infrastructure tools detected.",
    )
    hiring_signals: list[str] = Field(
        default_factory=list,
        description="Open engineering/product roles or technical requirements from job postings.",
    )
    inferred_infrastructure_needs: str = Field(
        description="Synthesis of the company's current architecture maturity and technical bottlenecks."
    )


class OutreachPitch(BaseModel):
    """B2B outreach deliverables including a Before/After comparison for LinkedIn showcases."""

    subject_line: str = Field(
        description="High-converting, specific B2B cold email subject line."
    )
    generic_ai_message: str = Field(
        description=(
            "The 'Before' baseline: a typical generic, superficial AI outreach message "
            "full of buzzwords to contrast against our multi-agent research."
        )
    )
    hyper_personalized_pitch: str = Field(
        description=(
            "The 'After' result: a concise, executive-ready outreach pitch referencing "
            "concrete press triggers, detected tech stack, and inferred pain points."
        )
    )
    icebreaker_hook: str = Field(
        description="Short 1-2 sentence LinkedIn connection request note (<300 characters)."
    )
    call_to_action: str = Field(
        description="Low-friction, value-first Call to Action (CTA)."
    )


class LeadReport(BaseModel):
    """Deterministic top-level output schema enforced via output_type=LeadReport."""

    company_name: str = Field(description="Official name of the target company.")
    target_domain: str = Field(description="Normalized primary domain or LinkedIn URL analyzed.")
    industry: str = Field(description="Primary B2B industry or vertical.")
    executive_summary: str = Field(
        description="2-3 sentence strategic overview of the company's current market position."
    )
    recent_news_and_triggers: list[str] = Field(
        min_length=1,
        description="Recent product launches, funding rounds, quarterly updates, or press releases.",
    )
    identified_pain_points: list[str] = Field(
        min_length=1,
        description="Actionable business or technical pain points deduced from news and hiring.",
    )
    tech_stack: TechStackAnalysis = Field(
        description="Structured tech-stack and hiring signal analysis."
    )
    outreach: OutreachPitch = Field(
        description="Tailored outreach pitch and Before/After comparison."
    )
    sources: list[SourceCitation] = Field(
        min_length=1,
        description="Verified source citations supporting the findings in this report.",
    )

