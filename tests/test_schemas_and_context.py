"""Unit tests for Pydantic schemas and Cost-Aware Routing telemetry math."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lead_agent.config import AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.schemas import (
    LeadReport,
    OutreachPitch,
    SourceCitation,
    TechStackAnalysis,
)


def test_source_citation_rejects_non_http_url() -> None:
    with pytest.raises(ValidationError):
        SourceCitation(
            title="Bad Link",
            url="ftp://files.example.com/doc.pdf",
            snippet="Invalid protocol",
        )


def test_cost_aware_routing_calculates_savings_accurately() -> None:
    settings = AgentSettings(
        fast_model="gpt-6-luna",
        reasoning_model="gpt-6.2-sol",
    )
    ctx = LeadRunContext(target_input="stripe.com", settings=settings)

    # Fast scraping agent: 10,000 input tokens, 1,000 output tokens
    fast_rec = ctx.record_agent_usage(
        agent_name="Company & News Agent",
        role="Scraping",
        model="gpt-6-luna",
        input_tokens=10_000,
        output_tokens=1_000,
        requests=2,
        latency_seconds=1.2,
    )
    assert fast_rec.tier == "fast"
    assert fast_rec.estimated_cost_usd < fast_rec.baseline_reasoning_cost_usd

    # Reasoning agent: 2,000 input tokens, 500 output tokens
    reas_rec = ctx.record_agent_usage(
        agent_name="Lead Orchestrator",
        role="Orchestration",
        model="gpt-6.2-sol",
        input_tokens=2_000,
        output_tokens=500,
        requests=1,
        latency_seconds=1.8,
    )
    assert reas_rec.tier == "reasoning"
    assert reas_rec.estimated_cost_usd == reas_rec.baseline_reasoning_cost_usd

    assert ctx.total_tokens == 13_500
    assert ctx.cost_savings_usd > 0
    assert ctx.cost_savings_pct > 50.0


def test_lead_report_schema_serialization() -> None:
    report = LeadReport(
        company_name="BMW Group",
        target_domain="https://www.bmwgroup.com/en",
        industry="Automotive",
        executive_summary="Global manufacturer of premium automobiles and motorcycles.",
        recent_news_and_triggers=["Expanded Neue Klasse EV production milestones."],
        identified_pain_points=["Supply chain and software-defined vehicle telemetry scale."],
        tech_stack=TechStackAnalysis(
            detected_technologies=["React", "TypeScript", "AWS", "Kubernetes"],
            hiring_signals=["Senior Cloud Architect (AWS / Kubernetes)"],
            inferred_infrastructure_needs="Connected vehicle telemetry processing at scale.",
        ),
        outreach=OutreachPitch(
            subject_line="Scaling EV telemetry for BMW's Neue Klasse architecture",
            generic_ai_message="Hi, I hope this email finds you well!",
            hyper_personalized_pitch=(
                "Noticed BMW Group's latest Neue Klasse EV milestones and cloud architecture hiring "
                "across AWS and Kubernetes. We help automotive platform teams optimize telemetry ingestion."
            ),
            icebreaker_hook="Impressed by BMW's Neue Klasse software-defined vehicle push—would love to connect!",
            call_to_action="Open to a 10-minute benchmark review?",
        ),
        sources=[
            SourceCitation(
                title="BMW Group Corporate Portal",
                url="https://www.bmwgroup.com/en",
                snippet="Official BMW Group corporate news and strategy.",
            )
        ],
    )
    dumped = report.model_dump()
    assert dumped["company_name"] == "BMW Group"
    assert len(dumped["sources"]) == 1
