"""Unit tests for the Lead Orchestrator and sub-agent wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from lead_agent.agents.orchestrator import (
    create_lead_orchestrator,
    run_lead_intelligence_pipeline,
)
from lead_agent.config import AgentSettings
from lead_agent.schemas import (
    LeadReport,
    OutreachPitch,
    SourceCitation,
    TechStackAnalysis,
)


def _sample_report() -> LeadReport:
    return LeadReport(
        company_name="Vercel",
        target_domain="https://vercel.com",
        industry="Cloud Developer Platform",
        executive_summary="Vercel builds the Frontend Cloud and Next.js ecosystem.",
        recent_news_and_triggers=["Launched Fluid Compute for concurrent AI workloads."],
        identified_pain_points=["Real-time token and compute cost attribution across tenants."],
        tech_stack=TechStackAnalysis(
            detected_technologies=["Next.js", "React", "TypeScript", "Rust"],
            hiring_signals=["Staff Systems Engineer (Rust / Go)"],
            inferred_infrastructure_needs="Low-overhead streaming telemetry.",
        ),
        outreach=OutreachPitch(
            subject_line="Sub-2ms telemetry joins for Vercel Fluid Compute",
            generic_ai_message="Hi Vercel team, hope you are doing great!",
            hyper_personalized_pitch=(
                "Following Vercel's Fluid Compute launch and your open Rust/Go runtime roles, "
                "we built a zero-overhead OpenTelemetry span join pattern for AI streaming workloads."
            ),
            icebreaker_hook="Huge fan of the Fluid Compute release—would love to connect!",
            call_to_action="Happy to share the Rust collector benchmark async.",
        ),
        sources=[
            SourceCitation(
                title="Vercel Blog",
                url="https://vercel.com/blog",
                snippet="Introducing Fluid Compute for AI workloads.",
            )
        ],
    )


def test_orchestrator_and_subagent_model_routing_configuration() -> None:
    settings = AgentSettings(
        fast_model="gpt-6-luna",
        reasoning_model="gpt-6.2-sol",
    )
    orchestrator = create_lead_orchestrator(settings=settings)
    assert orchestrator.name == "Lead Orchestrator"
    assert orchestrator.model == "gpt-6.2-sol"
    tool_names = [getattr(t, "name", "") for t in orchestrator.tools]
    assert "company_news_research_tool" in tool_names
    assert "tech_stack_detection_tool" in tool_names
    assert "outreach_copywriter_tool" in tool_names

    # Verify disabling a sub-agent or guardrail via settings updates the orchestrator
    selective_settings = AgentSettings(
        enable_tech_stack_agent=False,
        enable_input_guardrail=False,
    )
    selective_orch = create_lead_orchestrator(settings=selective_settings)
    selective_tools = [getattr(t, "name", "") for t in selective_orch.tools]
    assert "tech_stack_detection_tool" not in selective_tools
    assert len(selective_orch.input_guardrails) == 0


async def test_run_lead_intelligence_pipeline_with_mocked_runner() -> None:
    sample_report = _sample_report()

    class FakeUsage:
        input_tokens = 3200
        output_tokens = 850
        requests = 2

    class FakeRawResponse:
        usage = FakeUsage()

    class FakeRunResult:
        raw_responses = [FakeRawResponse()]
        context_wrapper = None

        def final_output_as(self, _cls):
            return sample_report

    with patch("lead_agent.agents.orchestrator.Runner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = FakeRunResult()
        report, ctx = await run_lead_intelligence_pipeline("vercel.com")

    assert report.company_name == "Vercel"
    assert ctx.total_tokens == 4050
    assert len(ctx.agent_records) == 1


async def test_pipeline_rejects_invalid_input_before_calling_runner() -> None:
    with patch("lead_agent.agents.orchestrator.Runner.run", new_callable=AsyncMock) as mock_run:
        with pytest.raises(ValueError, match="not a valid company domain"):
            await run_lead_intelligence_pipeline("random chat message with no url")
        mock_run.assert_not_called()
