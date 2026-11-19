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
        description="Original publication date (YYYY-MM-DD) if detected, else empty string.",
    )
    updated_date: str = Field(
        default="",
        description="Last-modified / updated date (YYYY-MM-DD) if detected, else empty string.",
    )
    age_days: int | None = Field(
        default=None,
        description="Actual age of the news item or source in days since publication.",
    )
    recency_score: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Temporal freshness score (0.0 to 1.0) calculated from actual age in days.",
    )
    credibility_score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Domain authority and provenance score from 0.0 to 1.0.",
    )
    source_quality_score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Quellenqualität: intrinsic authority and temporal freshness of the source (0.0 to 1.0).",
    )
    statement_quality_score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Aussagequalität: trigger density, factual specificity, and entity relevance of the statement (0.0 to 1.0).",
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
        description="Weighted overall quality score combining source_quality_score and statement_quality_score (0.0 to 1.0).",
    )

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            raise ValueError(f"Source URL must start with http:// or https://, got: {cleaned}")
        return cleaned


class VerifiedClaim(BaseModel):
    """Fact-checked claim mapped to a re-fetched source passage, semantic score, and grounding status."""

    claim: str = Field(description="The factual claim, summary, tech-stack statement, or pain point being verified.")
    category: str = Field(
        default="news_trigger",
        description="Claim category: 'executive_summary', 'news_trigger', 'pain_point', or 'tech_stack'.",
    )
    source_title: str = Field(
        default="",
        description="Title of the matched source reference.",
    )
    source_url: str = Field(
        description="HTTP/HTTPS URL of the source against which the claim was verified."
    )
    source_refetched: bool = Field(
        default=True,
        description="True only if the source URL was successfully re-fetched over HTTP during verification.",
    )
    matched_excerpt: str = Field(
        default="",
        description="Relevant passage extracted from the re-fetched original source text.",
    )
    semantic_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Semantic concept, n-gram, and negation-aware similarity score (0.0 to 1.0).",
    )
    grounding_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Combined lexical, entity, and semantic support score (0.0 to 1.0) against the source passage.",
    )
    verification_status: str = Field(
        default="verified",
        description="Status: 'verified', 'partially_supported', or 'inferred_hypothesis'.",
    )


class DetectedTechnology(BaseModel):
    """Evidence-backed technology detection with confidence, provenance, timestamp, and status."""

    name: str = Field(description="Name of the detected or inferred technology (e.g., 'Next.js', 'Kubernetes').")
    confidence_score: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0 to 1.0) based on signal provenance and corroboration.",
    )
    signal_source: str = Field(
        default="dom_or_header_inspection",
        description=(
            "Exact signal source: e.g. 'http_header (server: cloudflare)', "
            "'script_asset (js.stripe.com)', 'meta_generator', 'job_posting_requirement (/careers)', "
            "or 'body_text_mention'."
        ),
    )
    detected_at: str = Field(
        default="",
        description="ISO-8601 UTC timestamp when the technology signal was detected.",
    )
    detection_status: str = Field(
        default="confirmed",
        description=(
            "Classification: 'confirmed' (sicher erkannt via HTTP headers, script/link assets, or DOM markers, "
            "confidence >= 0.80) or 'suspected' (vermutet via job postings or body text mentions)."
        ),
    )


class TechStackAnalysis(BaseModel):
    """Technical footprint and engineering hiring intelligence."""

    detected_technologies: list[str] = Field(
        default_factory=list,
        description="Summary list of all detected and inferred technologies.",
    )
    technology_signals: list[DetectedTechnology] = Field(
        default_factory=list,
        description=(
            "Granular technology detections with confidence score, signal source, "
            "timestamp, and confirmed vs. suspected classification."
        ),
    )
    hiring_signals: list[str] = Field(
        default_factory=list,
        description="Open engineering/product roles or technical requirements from job postings.",
    )
    inferred_infrastructure_needs: str = Field(
        description="Synthesis of the company's current architecture maturity and technical bottlenecks."
    )


class OutreachPitch(BaseModel):
    """B2B outreach deliverables including email pitch, DM hook, CTA, and phone call memory notices."""

    subject_line: str = Field(
        description="High-converting, specific B2B cold email subject line."
    )
    generic_ai_message: str = Field(
        default="",
        description="Deprecated/optional baseline message field kept for backward compatibility.",
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
    phone_call_bullet_points: list[str] = Field(
        default_factory=list,
        description=(
            "4-5 concise bullet-point memory notices for a short B2B phone call: "
            "1) Opening trigger/news hook, 2) Key tech-stack or hiring signal to mention, "
            "3) Core pain-point hypothesis, 4) High-impact discovery question to ask, "
            "5) Low-friction next step."
        ),
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
