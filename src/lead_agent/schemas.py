"""Pydantic v2 structured output schemas for the B2B Lead Intelligence & Outreach Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SourceCitation(BaseModel):
    """Verified external source citation with deterministic provenance and relevance scoring."""

    title: str = Field(
        description="Title or clear description of the cited webpage, press release, job posting, or article."
    )
    url: str = Field(
        description="Full HTTP/HTTPS URL of the source (newsroom, press wire, RSS article, job board)."
    )
    snippet: str = Field(
        description="Concise factual quote or takeaway extracted from this source."
    )
    source_type: str = Field(
        default="corporate_website",
        description=(
            "Category of the source: 'official_newsroom', 'press_release', 'external_news', "
            "'rss_feed', 'careers_portal', or 'corporate_website'."
        ),
    )
    published_date: str = Field(
        default="",
        description="Publication or last-updated date (YYYY-MM-DD) if detected, else empty string.",
    )
    credibility_score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Domain authority and provenance score from 0.0 to 1.0.",
    )
    relevance_score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="B2B trigger density and company relevance score from 0.0 to 1.0.",
    )
    composite_score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Weighted overall source quality score (credibility + relevance + recency) from 0.0 to 1.0.",
    )

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            raise ValueError(f"Source URL must start with http:// or https://, got: {cleaned}")
        return cleaned


class VerifiedClaim(BaseModel):
    """Fact-checked claim mapped to a re-fetched source passage and grounding score."""

    claim: str = Field(description="The factual claim or pain point statement being verified.")
    category: str = Field(
        default="news_trigger",
        description="Claim category: 'news_trigger' or 'pain_point'.",
    )
    source_title: str = Field(
        default="",
        description="Title of the matched source reference.",
    )
    source_url: str = Field(
        description="HTTP/HTTPS URL of the source against which the claim was verified."
    )
    matched_excerpt: str = Field(
        default="",
        description="Relevant passage extracted from the re-fetched original source text.",
    )
    grounding_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Lexical and high-signal entity support score (0.0 to 1.0) against the source passage.",
    )
    verification_status: str = Field(
        default="verified",
        description="Status: 'verified', 'partially_supported', or 'inferred_hypothesis'.",
    )


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
    """B2B outreach deliverables including a Baseline vs. Multi-Agent Grounded comparison."""

    subject_line: str = Field(
        description="High-converting, specific B2B cold email subject line."
    )
    generic_ai_message: str = Field(
        description=(
            "Standard single-prompt baseline: a typical generic, superficial AI outreach message "
            "without live press or tech-stack grounding."
        )
    )
    hyper_personalized_pitch: str = Field(
        description=(
            "Multi-agent grounded result: a concise, executive-ready outreach pitch referencing "
            "concrete press triggers, detected tech stack, and inferred pain points."
        )
    )
    icebreaker_hook: str = Field(
        description="Short 1-2 sentence direct message icebreaker note (<300 characters)."
    )
    call_to_action: str = Field(
        description="Low-friction, value-first Call to Action (CTA)."
    )


class LeadReport(BaseModel):
    """Deterministic top-level output schema enforced via output_type=LeadReport."""

    company_name: str = Field(description="Official name of the target company.")
    target_domain: str = Field(description="Normalized primary domain or corporate URL analyzed.")
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
        description="Tailored outreach pitch and Baseline vs. Multi-Agent comparison."
    )
    sources: list[SourceCitation] = Field(
        min_length=1,
        description="Verified, quality-scored source citations supporting the findings in this report.",
    )
    verified_claims: list[VerifiedClaim] = Field(
        default_factory=list,
        description="5-step fact-check audit mapping each claim to its re-fetched source excerpt and grounding score.",
    )
