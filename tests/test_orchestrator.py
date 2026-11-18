"""Unit tests for the Lead Orchestrator and sub-agent wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from lead_agent.agents.orchestrator import (
    create_lead_orchestrator,
    run_lead_intelligence_pipeline,
)
from lead_agent.config import AgentSettings
from lead_agent.showcase import build_showcase_run


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


async def test_run_lead_intelligence_pipeline_with_mocked_runner() -> None:
    sample_report, _ = build_showcase_run("vercel.com")

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

