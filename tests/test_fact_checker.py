"""Unit tests for the 5-Step Fact-Verification & Claim-Grounding Engine."""

from __future__ import annotations

from lead_agent.config import AgentSettings
from lead_agent.fact_checker import (
    HYPOTHESIS_PREFIX,
    extract_best_matching_passage,
    verify_and_ground_lead_report,
)
from lead_agent.schemas import (
    LeadReport,
    OutreachPitch,
    SourceCitation,
    TechStackAnalysis,
)


def _build_test_report() -> LeadReport:
    return LeadReport(
        company_name="AcmeCloud",
        target_domain="https://acmecloud.io",
        industry="Cloud Infrastructure",
        executive_summary="AcmeCloud provides enterprise data streaming.",
        recent_news_and_triggers=[
            "AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec.",
            "AcmeCloud is building a nuclear fusion submarine fleet in Antarctica.",
        ],
        identified_pain_points=[
            "High cross-region Kafka replication latency on Kubernetes clusters.",
            "Interplanetary Mars satellite bandwidth constraints.",
        ],
        tech_stack=TechStackAnalysis(
            detected_technologies=["Kafka", "Snowflake", "Kubernetes"],
            hiring_signals=["Staff Distributed Systems Engineer (Go / Kafka)"],
            inferred_infrastructure_needs="Low-latency stream processing.",
        ),
        outreach=OutreachPitch(
            subject_line="Zero-Copy Snowflake Connector latency at AcmeCloud",
            generic_ai_message="Hi AcmeCloud, hope this finds you well!",
            hyper_personalized_pitch=(
                "Saw AcmeCloud's Zero-Copy Snowflake Connector launch processing 5M events/sec "
                "and your open Kafka/Kubernetes engineering roles."
            ),
            icebreaker_hook="Congrats on the Zero-Copy Snowflake Connector release!",
            call_to_action="Open to a 10-minute benchmark review?",
        ),
        sources=[
            SourceCitation(
                title="AcmeCloud Q3 Release Notes",
                url="https://acmecloud.io/news/q3-release",
                snippet="AcmeCloud launches Zero-Copy Snowflake Connector.",
            )
        ],
    )


def test_extract_best_matching_passage_finds_relevant_sentence() -> None:
    original_document = (
        "Welcome to AcmeCloud corporate portal. "
        "In Q3 2026, AcmeCloud officially launched its Zero-Copy Snowflake Connector "
        "capable of processing 5M events/sec across multi-region Kubernetes clusters. "
        "Contact our sales office in Munich for pricing."
    )
    claim = "AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec."
    passage, score = extract_best_matching_passage(claim, original_document)

    assert "Zero-Copy Snowflake Connector" in passage
    assert "5M events/sec" in passage
    assert score >= 0.55


async def test_verify_and_ground_lead_report_marks_unverified_claims_as_hypothesis() -> None:
    report = _build_test_report()

    async def fake_fetcher(_url: str) -> str:
        return (
            "AcmeCloud Q3 Press Release. Today AcmeCloud launched a Zero-Copy Snowflake Connector "
            "processing 5M events/sec. Engineering teams are optimizing cross-region Kafka "
            "replication latency on Kubernetes clusters."
        )

    settings = AgentSettings(
        enable_fact_checking=True,
        min_grounding_score=0.25,
        unverified_claim_policy="mark_as_hypothesis",
    )
    verified_report = await verify_and_ground_lead_report(
        report,
        settings=settings,
        custom_fetcher=fake_fetcher,
    )

    assert len(verified_report.verified_claims) == 4
    statuses = {vc.claim: vc.verification_status for vc in verified_report.verified_claims}

    assert (
        statuses["AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec."]
        == "verified"
    )
    assert (
        statuses["AcmeCloud is building a nuclear fusion submarine fleet in Antarctica."]
        == "inferred_hypothesis"
    )

    # Grounded claim stays untouched; unverified claim is prefixed with [Hypothesis / Inferred]
    assert (
        verified_report.recent_news_and_triggers[0]
        == "AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec."
    )
    assert verified_report.recent_news_and_triggers[1].startswith(HYPOTHESIS_PREFIX)
    assert verified_report.identified_pain_points[1].startswith(HYPOTHESIS_PREFIX)


async def test_verify_and_ground_lead_report_discards_unverified_claims_when_configured() -> None:
    report = _build_test_report()

    async def fake_fetcher(_url: str) -> str:
        return (
            "AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec. "
            "Teams face high cross-region Kafka replication latency on Kubernetes clusters."
        )

    settings = AgentSettings(
        enable_fact_checking=True,
        min_grounding_score=0.25,
        unverified_claim_policy="discard",
    )
    verified_report = await verify_and_ground_lead_report(
        report,
        settings=settings,
        custom_fetcher=fake_fetcher,
    )

    # Unverified submarine and Mars claims were discarded, keeping only the grounded claims
    assert len(verified_report.recent_news_and_triggers) == 1
    assert "Snowflake Connector" in verified_report.recent_news_and_triggers[0]
    assert len(verified_report.identified_pain_points) == 1
    assert "Kafka replication latency" in verified_report.identified_pain_points[0]
