"""Unit tests for the 5-Step Semantic Fact-Verification & Claim-Grounding Engine."""

from __future__ import annotations

from lead_agent.config import AgentSettings
from lead_agent.fact_checker import (
    HYPOTHESIS_PREFIX,
    PARTIALLY_SUPPORTED_PREFIX,
    _apply_unverified_policy_to_claims,
    compute_semantic_similarity,
    extract_best_matching_passage,
    verify_and_ground_lead_report,
)
from lead_agent.schemas import (
    DetectedTechnology,
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
        executive_summary="AcmeCloud provides enterprise data streaming on Kubernetes clusters.",
        recent_news_and_triggers=[
            "AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec.",
            "AcmeCloud announced a European banking data streaming expansion in Zurich.",
            "AcmeCloud is building a nuclear fusion submarine fleet in Antarctica.",
        ],
        identified_pain_points=[
            "High cross-region Kafka replication latency on Kubernetes clusters.",
            "Interplanetary Mars satellite bandwidth constraints.",
        ],
        tech_stack=TechStackAnalysis(
            detected_technologies=["Kafka", "Snowflake", "Kubernetes"],
            hiring_signals=["Staff Distributed Systems Engineer (Go / Kafka)"],
            inferred_infrastructure_needs="Low-latency stream processing on Kubernetes and Kafka.",
        ),
        outreach=OutreachPitch(
            subject_line="Zero-Copy Snowflake Connector latency at AcmeCloud",
            generic_ai_message="",
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
    passage, grounding_score, semantic_score = extract_best_matching_passage(
        claim, original_document
    )

    assert "Zero-Copy Snowflake Connector" in passage
    assert "5M events/sec" in passage
    assert grounding_score >= 0.55
    assert semantic_score >= 0.50


def test_semantic_similarity_handles_paraphrases_and_negations() -> None:
    # Paraphrase using different words from the same B2B semantic concept clusters
    claim = "Scaling electric vehicle manufacturing plants and cloud telemetry."
    paraphrased_passage = (
        "The automotive group is expanding EV production facilities with AWS observability pipelines."
    )
    unrelated_passage = "Quarterly bakery pastry recipe instructions for chocolate croissants."
    negated_passage = (
        "The company is NOT scaling electric vehicle manufacturing plants or cloud telemetry."
    )

    sim_paraphrase = compute_semantic_similarity(claim, paraphrased_passage)
    sim_unrelated = compute_semantic_similarity(claim, unrelated_passage)
    sim_negated = compute_semantic_similarity(claim, negated_passage)

    assert sim_paraphrase > sim_unrelated + 0.25
    assert sim_negated < sim_paraphrase


async def test_successful_refetch_is_required_for_verified_status() -> None:
    report = _build_test_report()

    # Simulate a failed HTTP re-fetch (returns empty text / refetch_succeeded=False)
    async def failed_fetcher(_url: str) -> tuple[str, bool]:
        return ("", False)

    settings = AgentSettings(
        enable_fact_checking=True,
        min_grounding_score=0.25,
        unverified_claim_policy="mark_as_hypothesis",
    )
    checked = await verify_and_ground_lead_report(
        report,
        settings=settings,
        custom_fetcher=failed_fetcher,
    )

    # Because re-fetch failed, NO claim may be marked as 'verified'
    for vc in checked.verified_claims:
        assert vc.source_refetched is False
        assert vc.verification_status != "verified"

    # The first claim matches the un-refetched snippet, so it is capped at 'partially_supported'
    assert checked.recent_news_and_triggers[0].startswith(PARTIALLY_SUPPORTED_PREFIX)


async def test_verify_all_sections_and_separate_partially_supported_labels() -> None:
    report = _build_test_report()

    async def fake_fetcher(_url: str) -> str:
        return (
            "AcmeCloud Q3 Press Release. AcmeCloud provides enterprise data streaming on Kubernetes clusters. "
            "Today AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec. "
            "Engineering teams are optimizing cross-region Kafka replication latency on Kubernetes clusters "
            "for low-latency stream processing."
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

    categories = {vc.category for vc in verified_report.verified_claims}
    # All 4 core sections must be audited: executive_summary, news_trigger, pain_point, tech_stack
    assert categories == {"executive_summary", "news_trigger", "pain_point", "tech_stack"}

    # 1. Fully verified trigger stays clean
    assert (
        verified_report.recent_news_and_triggers[0]
        == "AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec."
    )
    # 2. Partially supported trigger gets [Partially Supported] prefix
    assert verified_report.recent_news_and_triggers[1].startswith(PARTIALLY_SUPPORTED_PREFIX)
    # 3. Unverified trigger gets [Hypothesis / Inferred] prefix
    assert verified_report.recent_news_and_triggers[2].startswith(HYPOTHESIS_PREFIX)


async def test_verify_and_ground_lead_report_discards_unverified_claims_when_configured() -> None:
    report = _build_test_report()

    async def fake_fetcher(_url: str) -> str:
        return (
            "AcmeCloud provides enterprise data streaming on Kubernetes clusters. "
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

    # Unverified submarine and Mars claims were discarded
    assert not any("submarine" in c for c in verified_report.recent_news_and_triggers)
    assert not any("Mars" in p for p in verified_report.identified_pain_points)
    assert "Snowflake Connector" in verified_report.recent_news_and_triggers[0]


def test_unmapped_claims_default_to_inferred_hypothesis_fail_closed() -> None:
    """Any claim without a matching verification record must fail closed to 'inferred_hypothesis'."""
    res_mark = _apply_unverified_policy_to_claims(
        ["Unmapped claim without verification record"],
        verified_records=[],
        policy="mark_as_hypothesis",
    )
    assert res_mark == [f"{HYPOTHESIS_PREFIX}Unmapped claim without verification record"]

    # When discard policy is active and a verified claim exists alongside an unmapped claim,
    # the unmapped claim must be discarded (never kept as 'verified').
    from lead_agent.schemas import VerifiedClaim

    verified_rec = VerifiedClaim(
        claim="Verified claim with record",
        source_url="https://acmecloud.io/news",
        source_refetched=True,
        verification_status="verified",
    )
    res_discard = _apply_unverified_policy_to_claims(
        ["Verified claim with record", "Unmapped mystery claim"],
        verified_records=[verified_rec],
        policy="discard",
    )
    assert res_discard == ["Verified claim with record"]

    # Also verify VerifiedClaim schema defaults are fail-closed ('inferred_hypothesis' and source_refetched=False)
    default_vc = VerifiedClaim(
        claim="Default status check",
        source_url="https://acmecloud.io/news",
    )
    assert default_vc.verification_status == "inferred_hypothesis"
    assert default_vc.source_refetched is False


async def test_individual_technology_verification_prevents_masking_unbacked_tech() -> None:
    """Verify that 3 valid technologies do NOT mask 1 unbacked technology claim, even if the LLM
    self-reported the unbacked technology as 'confirmed' (0.95) in technology_signals.
    """
    report = _build_test_report()
    report = report.model_copy(
        update={
            "tech_stack": report.tech_stack.model_copy(
                update={
                    "detected_technologies": [
                        "Kafka",
                        "Snowflake",
                        "Kubernetes",
                        "QuantumMainframeOS",
                    ],
                    "technology_signals": [
                        DetectedTechnology(
                            name="Kafka",
                            confidence_score=0.92,
                            signal_source="job_posting_requirement",
                            detection_status="confirmed",
                        ),
                        DetectedTechnology(
                            name="QuantumMainframeOS",
                            confidence_score=0.95,
                            signal_source="script_asset",
                            detection_status="confirmed",
                        ),
                        DetectedTechnology(
                            name="SecretCobolEngine",
                            confidence_score=0.91,
                            signal_source="http_header",
                            detection_status="confirmed",
                        ),
                    ],
                }
            )
        }
    )

    async def fake_fetcher(_url: str) -> str:
        return (
            "AcmeCloud provides enterprise data streaming on Kubernetes clusters. "
            "AcmeCloud launched a Zero-Copy Snowflake Connector processing 5M events/sec "
            "with low-latency Kafka stream replication."
        )

    # 1. With mark_as_hypothesis: QuantumMainframeOS and SecretCobolEngine are individually flagged
    marked_report = await verify_and_ground_lead_report(
        report,
        settings=AgentSettings(unverified_claim_policy="mark_as_hypothesis"),
        custom_fetcher=fake_fetcher,
    )
    assert "Kafka" in marked_report.tech_stack.detected_technologies
    assert "Snowflake" in marked_report.tech_stack.detected_technologies
    assert "Kubernetes" in marked_report.tech_stack.detected_technologies
    assert f"{HYPOTHESIS_PREFIX}QuantumMainframeOS" in marked_report.tech_stack.detected_technologies

    tech_claims = {
        vc.claim: vc.verification_status
        for vc in marked_report.verified_claims
        if vc.category == "tech_stack"
    }
    assert tech_claims["Technology: Kafka"] == "verified"
    assert tech_claims["Technology: Snowflake"] == "verified"
    assert tech_claims["Technology: Kubernetes"] == "verified"
    assert tech_claims["Technology: QuantumMainframeOS"] == "inferred_hypothesis"
    assert tech_claims["Technology: SecretCobolEngine"] == "inferred_hypothesis"

    # Both unbacked signals in technology_signals must be downgraded to 'suspected' (<= 0.35)
    sig_map = {s.name: s for s in marked_report.tech_stack.technology_signals}
    assert sig_map["QuantumMainframeOS"].detection_status == "suspected"
    assert sig_map["QuantumMainframeOS"].confidence_score <= 0.35
    assert sig_map["SecretCobolEngine"].detection_status == "suspected"
    assert sig_map["SecretCobolEngine"].confidence_score <= 0.35

    # 2. With discard policy: unbacked technologies are removed from both lists
    discarded_report = await verify_and_ground_lead_report(
        report,
        settings=AgentSettings(unverified_claim_policy="discard"),
        custom_fetcher=fake_fetcher,
    )
    assert discarded_report.tech_stack.detected_technologies == [
        "Kafka",
        "Snowflake",
        "Kubernetes",
    ]
    assert [s.name for s in discarded_report.tech_stack.technology_signals] == ["Kafka"]

