"""Unit tests for Pydantic schemas, Cost-Aware Routing math, and Showcase execution."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lead_agent.config import AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.schemas import SourceCitation
from lead_agent.showcase import build_showcase_run


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


def test_showcase_run_presets_and_dynamic_domains() -> None:
    report_stripe, ctx_stripe = build_showcase_run("stripe.com")
    assert report_stripe.company_name == "Stripe"
    assert len(ctx_stripe.agent_records) == 4
    assert ctx_stripe.cost_savings_pct > 60.0

    report_custom, ctx_custom = build_showcase_run("personio.de")
    assert report_custom.company_name == "Personio"
    assert report_custom.target_domain == "https://personio.de"
    assert len(report_custom.sources) >= 1

    with pytest.raises(ValueError, match="not a valid company domain"):
        build_showcase_run("invalid non-domain text")

