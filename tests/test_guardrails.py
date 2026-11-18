"""Unit tests for Input and Output Guardrails."""

from __future__ import annotations

import pytest

from lead_agent.config import AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.guardrails import (
    validate_lead_input,
    validate_lead_input_guardrail,
    validate_lead_output,
    validate_lead_output_guardrail,
)
from lead_agent.schemas import (
    LeadReport,
    OutreachPitch,
    SourceCitation,
    TechStackAnalysis,
)


class DummyContextWrapper:
    def __init__(self, context: LeadRunContext) -> None:
        self.context = context


def _make_valid_report() -> LeadReport:
    return LeadReport(
        company_name="Stripe",
        target_domain="https://stripe.com",
        industry="FinTech",
        executive_summary="Stripe builds programmable financial infrastructure for the internet.",
        recent_news_and_triggers=["Launched usage-based billing metering for AI startups."],
        identified_pain_points=["High-cardinality telemetry costs on real-time event streams."],
        tech_stack=TechStackAnalysis(
            detected_technologies=["React", "Go", "Kafka", "AWS"],
            hiring_signals=["Staff Distributed Systems Engineer (Go/Kafka)"],
            inferred_infrastructure_needs="Low-latency stream aggregation.",
        ),
        outreach=OutreachPitch(
            subject_line="Cutting Kafka telemetry overhead on Stripe Billing",
            generic_ai_message="Hi Stripe, I hope this email finds you well!",
            hyper_personalized_pitch=(
                "Saw Stripe's recent usage-based billing launch and your Staff Go/Kafka openings. "
                "We helped a similar payments team cut high-cardinality telemetry volume by 42%."
            ),
            icebreaker_hook="Loved the recent Stripe Billing metering announcement—would love to connect!",
            call_to_action="Open to a 1-page architecture teardown?",
        ),
        sources=[
            SourceCitation(
                title="Stripe Newsroom",
                url="https://stripe.com/newsroom",
                snippet="Usage-based billing release.",
            )
        ],
    )


@pytest.mark.parametrize(
    ("raw_input", "expected_normalized"),
    [
        ("stripe.com", "https://stripe.com"),
        ("https://vercel.com/careers", "https://vercel.com/careers"),
        ("www.celonis.com", "https://www.celonis.com"),
        (
            "https://www.linkedin.com/company/openai",
            "https://www.linkedin.com/company/openai",
        ),
        ("Analyze stripe.com please", "https://stripe.com"),
    ],
)
def test_validate_lead_input_accepts_valid_domains_and_urls(
    raw_input: str, expected_normalized: str
) -> None:
    outcome = validate_lead_input(raw_input)
    assert outcome.is_valid is True
    assert outcome.normalized_target == expected_normalized


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "   ",
        "tell me a joke about sales",
        "http://localhost:8000",
        "https://127.0.0.1/admin",
        "corp.internal",
        "a" * 350,
    ],
)
def test_validate_lead_input_blocks_invalid_or_local_inputs(invalid_input: str) -> None:
    outcome = validate_lead_input(invalid_input)
    assert outcome.is_valid is False


async def test_input_guardrail_decorator_sets_tripwire() -> None:
    ctx = DummyContextWrapper(LeadRunContext(target_input="invalid prompt"))
    fn = getattr(validate_lead_input_guardrail, "guardrail_function", validate_lead_input_guardrail)
    res_bad = await fn(ctx, None, "just some random words without a domain")
    assert res_bad.tripwire_triggered is True

    res_good = await fn(ctx, None, "stripe.com")
    assert res_good.tripwire_triggered is False


def test_validate_lead_output_passes_and_catches_spam() -> None:
    report = _make_valid_report()
    assert validate_lead_output(report).is_valid is True

    spam_report = report.model_copy(
        update={
            "outreach": report.outreach.model_copy(
                update={
                    "hyper_personalized_pitch": (
                        "We offer guaranteed 10x returns and 100% free money if you act now before it's too late!"
                    )
                }
            )
        }
    )
    outcome = validate_lead_output(spam_report)
    assert outcome.is_valid is False
    assert "spam phrase" in outcome.reason.lower()


async def test_output_guardrail_decorator() -> None:
    ctx = DummyContextWrapper(LeadRunContext(target_input="stripe.com"))
    report = _make_valid_report()
    fn = getattr(validate_lead_output_guardrail, "guardrail_function", validate_lead_output_guardrail)
    res = await fn(ctx, None, report)
    assert res.tripwire_triggered is False


def test_configurable_guardrail_settings() -> None:
    # Private IP allowed when block_private_ips=False
    allow_local_settings = AgentSettings(block_private_ips=False)
    assert validate_lead_input("http://localhost:8000", settings=allow_local_settings).is_valid is True

    # Input guardrail completely bypassed when enable_input_guardrail=False
    disabled_input_settings = AgentSettings(enable_input_guardrail=False)
    assert validate_lead_input("arbitrary text target", settings=disabled_input_settings).is_valid is True

    # Output guardrail custom min_sources_required and custom blocked phrase
    report = _make_valid_report()
    strict_sources = AgentSettings(min_sources_required=3)
    assert validate_lead_output(report, settings=strict_sources).is_valid is False

    custom_spam = AgentSettings(blocked_spam_phrases=("payments team",))
    assert validate_lead_output(report, settings=custom_spam).is_valid is False


