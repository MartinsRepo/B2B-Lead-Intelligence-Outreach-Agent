"""Lead Orchestrator Agent using the OpenAI Agents SDK (.as_tool() pattern)."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

try:
    from agents import Agent, AgentHooks, RunContextWrapper, Runner
except ImportError:  # pragma: no cover
    Agent = Any  # type: ignore[misc,assignment]
    RunContextWrapper = Any  # type: ignore[misc,assignment]
    Runner = Any  # type: ignore[misc,assignment]

    class AgentHooks:  # type: ignore[no-redef]
        pass


from lead_agent.agents.company_news_agent import create_company_news_agent
from lead_agent.agents.copywriter_agent import create_copywriter_agent
from lead_agent.agents.tech_stack_agent import create_tech_stack_agent
from lead_agent.config import DEFAULT_SETTINGS, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.fact_checker import verify_and_ground_lead_report
from lead_agent.guardrails import (
    validate_lead_input,
    validate_lead_input_guardrail,
    validate_lead_output,
    validate_lead_output_guardrail,
)
from lead_agent.privacy import (
    DEFAULT_OPT_OUT_MANAGER,
    compute_retention_timestamps,
    detect_misleading_advertising_claims,
    get_art14_outreach_footer,
    scrub_personal_data,
)
from lead_agent.schemas import (
    AdvertisingComplianceRecord,
    DetectedTechnology,
    LeadReport,
    SourceCitation,
)
from lead_agent.tools.research_engine import evaluate_source_quality
from lead_agent.tools.tech_parser import classify_tech_status, utc_now_iso

ORCHESTRATOR_INSTRUCTIONS = """You are the Lead Orchestrator Agent controlling an autonomous B2B Lead Intelligence & Outreach workflow.

Your workflow MUST follow these steps using your available sub-agent tools:
1. If `company_news_research_tool` is available, invoke it with the target domain or corporate URL to gather company overview, recent press releases/news, and source links.
2. If `tech_stack_detection_tool` is available, invoke it with the target domain or URL to detect their web/cloud stack and engineering hiring signals from job postings.
3. If `outreach_copywriter_tool` is available, pass the combined intelligence to it to generate the 'Before' (generic AI baseline) vs. 'After' (hyper-personalized) outreach pitch and short-form icebreaker hook.
4. Synthesize all findings into the final `LeadReport` structured schema, ensuring every claim is backed by verified HTTP/HTTPS URLs in `sources`."""


class TelemetryAgentHooks(AgentHooks[LeadRunContext]):  # type: ignore[misc]
    """Lifecycle hooks capturing per-agent latency and token telemetry into LeadRunContext."""

    def __init__(self, role_label: str, model_name: str) -> None:
        self.role_label = role_label
        self.model_name = model_name
        self._start_times: dict[int, float] = {}
        self._usage_snapshots: dict[int, tuple[int, int, int]] = {}

    async def on_start(
        self, context: RunContextWrapper[LeadRunContext], agent: Agent[LeadRunContext]
    ) -> None:
        key = id(agent)
        self._start_times[key] = time.perf_counter()
        usage = getattr(context, "usage", None)
        if usage is not None:
            self._usage_snapshots[key] = (
                int(getattr(usage, "input_tokens", 0) or 0),
                int(getattr(usage, "output_tokens", 0) or 0),
                int(getattr(usage, "requests", 0) or 0),
            )
        if hasattr(context, "context") and isinstance(context.context, LeadRunContext):
            context.context.log_tool_event(
                f"Agent started: {agent.name} [{self.model_name}]"
            )

    async def on_end(
        self,
        context: RunContextWrapper[LeadRunContext],
        agent: Agent[LeadRunContext],
        output: Any,
    ) -> None:
        key = id(agent)
        started = self._start_times.pop(key, time.perf_counter())
        elapsed = max(0.01, time.perf_counter() - started)

        prev_in, prev_out, prev_req = self._usage_snapshots.pop(key, (0, 0, 0))
        usage = getattr(context, "usage", None)
        cur_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        cur_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        cur_req = int(getattr(usage, "requests", 0) or 0) if usage else 0

        delta_in = max(0, cur_in - prev_in)
        delta_out = max(0, cur_out - prev_out)
        delta_req = max(1, cur_req - prev_req)

        if hasattr(context, "context") and isinstance(context.context, LeadRunContext):
            context.context.record_agent_usage(
                agent_name=agent.name,
                role=self.role_label,
                model=self.model_name,
                input_tokens=delta_in,
                output_tokens=delta_out,
                requests=delta_req,
                latency_seconds=elapsed,
            )
            context.context.log_tool_event(
                f"Agent completed: {agent.name} ({delta_in + delta_out} tokens in {elapsed:.2f}s)"
            )


LIVE_MODEL_ALIASES: dict[str, str] = {
    "gpt-6-luna": "gpt-4o-mini",
    "gpt-6.2-sol": "gpt-4o",
}


def resolve_live_model_name(configured_model: str) -> str:
    """Map conceptual architecture model IDs to live OpenAI API model IDs when needed."""
    return LIVE_MODEL_ALIASES.get(configured_model.strip().lower(), configured_model)


def create_lead_orchestrator(
    settings: AgentSettings = DEFAULT_SETTINGS,
    resolve_aliases: bool = False,
) -> Agent[LeadRunContext]:
    """Assemble the multi-agent hierarchy using the OpenAI Agents SDK .as_tool() pattern."""
    effective_settings = (
        replace(
            settings,
            fast_model=resolve_live_model_name(settings.fast_model),
            reasoning_model=resolve_live_model_name(settings.reasoning_model),
        )
        if resolve_aliases
        else settings
    )

    subagent_tools: list[Any] = []

    if settings.enable_company_news_agent:
        company_agent = create_company_news_agent(
            settings=effective_settings,
            hooks=TelemetryAgentHooks(
                role_label="Scraping & News Extraction", model_name=settings.fast_model
            ),
        )
        subagent_tools.append(
            company_agent.as_tool(
                tool_name="company_news_research_tool",
                tool_description=(
                    "Scrapes the target company's website, press releases, and recent news "
                    "using the fast extraction model."
                ),
            )
        )

    if settings.enable_tech_stack_agent:
        tech_agent = create_tech_stack_agent(
            settings=effective_settings,
            hooks=TelemetryAgentHooks(
                role_label="Tech-Stack & Job-Board Parsing", model_name=settings.fast_model
            ),
        )
        subagent_tools.append(
            tech_agent.as_tool(
                tool_name="tech_stack_detection_tool",
                tool_description=(
                    "Detects the target company's frontend/cloud tech stack and scans job "
                    "postings for engineering hiring signals using the fast extraction model."
                ),
            )
        )

    if settings.enable_copywriter_agent:
        copywriter_agent = create_copywriter_agent(
            settings=effective_settings,
            hooks=TelemetryAgentHooks(
                role_label="Executive Pitch Synthesis", model_name=settings.reasoning_model
            ),
        )
        subagent_tools.append(
            copywriter_agent.as_tool(
                tool_name="outreach_copywriter_tool",
                tool_description=(
                    "Synthesizes company news and tech stack signals into a Before/After "
                    "B2B outreach pitch using the reasoning model."
                ),
            )
        )

    orchestrator_hooks = TelemetryAgentHooks(
        role_label="Workflow Orchestration & Structuring",
        model_name=settings.reasoning_model,
    )

    input_guardrails = (
        [validate_lead_input_guardrail] if settings.enable_input_guardrail else []
    )
    output_guardrails = (
        [validate_lead_output_guardrail] if settings.enable_output_guardrail else []
    )

    return Agent[LeadRunContext](
        name="Lead Orchestrator",
        model=effective_settings.reasoning_model,
        instructions=ORCHESTRATOR_INSTRUCTIONS,
        tools=subagent_tools,
        input_guardrails=input_guardrails,
        output_guardrails=output_guardrails,
        output_type=LeadReport,
        hooks=orchestrator_hooks,
    )


async def run_lead_intelligence_pipeline(
    target_input: str,
    settings: AgentSettings = DEFAULT_SETTINGS,
) -> tuple[LeadReport, LeadRunContext]:
    """Execute the full Lead Intelligence & Outreach Agent workflow with guardrails and telemetry."""
    run_context = LeadRunContext(target_input=target_input, settings=settings)

    # Pre-flight deterministic input check (matches Input Guardrail logic)
    precheck = validate_lead_input(target_input, settings=settings)
    if not precheck.is_valid:
        run_context.log_tool_event(f"Input Guardrail Tripwire -> {precheck.reason}")
        raise ValueError(precheck.reason)

    # Ensure the SDK's default AsyncOpenAI client is bound to the currently active event loop
    try:
        import os

        from agents import set_default_openai_client
        from openai import AsyncOpenAI

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key and not api_key.startswith("sk-YOUR_"):
            set_default_openai_client(AsyncOpenAI(api_key=api_key), use_for_tracing=True)
    except Exception:
        pass

    orchestrator = create_lead_orchestrator(settings=settings, resolve_aliases=True)
    start_ts = time.perf_counter()
    result = await Runner.run(
        starting_agent=orchestrator,
        input=f"Analyze target B2B company and generate LeadReport for: {precheck.normalized_target}",
        context=run_context,
    )
    elapsed = time.perf_counter() - start_ts

    report: LeadReport = result.final_output_as(LeadReport)

    # Deterministically evaluate & rank every source citation in LeadReport
    enriched_sources: list[SourceCitation] = []
    for src in report.sources:
        evaluated = evaluate_source_quality(
            title=src.title,
            url=src.url,
            snippet=src.snippet,
            target_domain=precheck.normalized_target,
            source_type=src.source_type,
            published_date=src.published_date,
            updated_date=src.updated_date,
        )
        enriched_sources.append(
            SourceCitation(
                title=evaluated.title,
                url=evaluated.url,
                snippet=evaluated.snippet,
                source_type=evaluated.source_type,
                published_date=evaluated.published_date,
                updated_date=evaluated.updated_date,
                age_days=evaluated.age_days,
                recency_score=evaluated.recency_score,
                credibility_score=evaluated.credibility_score,
                source_quality_score=evaluated.source_quality_score,
                statement_quality_score=evaluated.statement_quality_score,
                relevance_score=evaluated.relevance_score,
                composite_score=evaluated.composite_score,
            )
        )
    enriched_sources.sort(key=lambda s: s.composite_score, reverse=True)
    report = report.model_copy(update={"sources": enriched_sources})

    # Normalize & enrich tech_stack.technology_signals (confidence, signal_source, detected_at, confirmed vs. suspected)
    now_ts = utc_now_iso()
    existing_signals: dict[str, DetectedTechnology] = {}
    for sig in report.tech_stack.technology_signals:
        norm_status = classify_tech_status(sig.confidence_score)
        existing_signals[sig.name.lower()] = sig.model_copy(
            update={
                "detected_at": sig.detected_at or now_ts,
                "detection_status": norm_status,
            }
        )

    hiring_blob = " ".join(report.tech_stack.hiring_signals).lower()
    for tech_name in report.tech_stack.detected_technologies:
        key = tech_name.lower()
        if key not in existing_signals:
            in_jobs = key in hiring_blob
            # Default un-signaled items to suspected (<0.80) until verified by fact_checker
            default_conf = 0.72 if in_jobs else 0.75
            default_src = (
                f"job_posting_requirement ({precheck.normalized_target}/careers)"
                if in_jobs
                else f"inferred_tech_mention ({precheck.normalized_target})"
            )
            existing_signals[key] = DetectedTechnology(
                name=tech_name,
                confidence_score=default_conf,
                signal_source=default_src,
                detected_at=now_ts,
                detection_status=classify_tech_status(default_conf),
            )

    sorted_tech_signals = sorted(
        existing_signals.values(),
        key=lambda t: (t.confidence_score, t.name),
        reverse=True,
    )
    report = report.model_copy(
        update={
            "tech_stack": report.tech_stack.model_copy(
                update={"technology_signals": sorted_tech_signals}
            )
        }
    )

    # Execute 5-step fact verification (re-fetch sources, extract passages, compare claims, mark/discard unverified)
    report = await verify_and_ground_lead_report(
        report,
        settings=settings,
        run_context=run_context,
    )

    # Ensure phone_call_bullet_points are always populated for the live call cheat-sheet
    if not report.outreach.phone_call_bullet_points:
        top_trigger = report.recent_news_and_triggers[0]
        top_pain = report.identified_pain_points[0]
        top_techs = ", ".join(report.tech_stack.detected_technologies[:5]) or "current cloud stack"
        top_role = (
            report.tech_stack.hiring_signals[0]
            if report.tech_stack.hiring_signals
            else "active engineering initiatives"
        )
        synthesized_bullets = [
            f"Opening Trigger Hook: Reference '{top_trigger}' to establish immediate relevance.",
            f"Tech & Hiring Context: Mention their footprint in {top_techs} alongside '{top_role}'.",
            f"Core Pain-Point Hypothesis: Validate whether '{top_pain}' is currently impacting team velocity.",
            f"Key Discovery Question: 'As {report.company_name} scales these initiatives, how is your team currently handling {report.tech_stack.inferred_infrastructure_needs.lower().rstrip('.')}?'",
            f"Low-Friction Close: {report.outreach.call_to_action}",
        ]
        report = report.model_copy(
            update={
                "outreach": report.outreach.model_copy(
                    update={"phone_call_bullet_points": synthesized_bullets}
                )
            }
        )

    # Apply GDPR Art. 5(1)(c) PII redaction, Art. 5(1)(e) retention timestamps, Art. 14 transparency footer,
    # and Advertising Law / Werberecht (§ 5 & § 7 UWG) provenance, consent & draft-only gate
    if settings.opt_out_domains:
        DEFAULT_OPT_OUT_MANAGER.sync_domains(settings.opt_out_domains)

    created_utc, expires_utc = compute_retention_timestamps(settings.retention_ttl_seconds)
    art14_footer = get_art14_outreach_footer(report.company_name)
    origin_urls = [src.url for src in report.sources]
    has_supported_claim = (
        any(
            vc.verification_status in ("verified", "partially_supported")
            for vc in report.verified_claims
        )
        if report.verified_claims
        else True
    )
    has_misleading = bool(
        detect_misleading_advertising_claims(
            " ".join(
                [
                    report.outreach.subject_line,
                    report.outreach.hyper_personalized_pitch,
                    report.outreach.icebreaker_hook,
                    report.outreach.call_to_action,
                ]
            ),
            prohibited_phrases=settings.blocked_misleading_claims,
        )
    )
    adv_compliance = AdvertisingComplianceRecord(
        auto_send_disabled=True,
        delivery_mode="draft_only_requires_legal_release",
        legal_approval_status="pending_legal_review",
        approved_by="",
        approved_at_utc="",
        consent_status=settings.default_consent_status,
        contact_origin_urls=origin_urls,
        origin_documented_at_utc=created_utc,
        substantiation_audit_passed=has_supported_claim and not has_misleading,
    )

    if settings.enable_pii_redaction:
        report = report.model_copy(
            update={
                "executive_summary": scrub_personal_data(report.executive_summary),
                "recent_news_and_triggers": [
                    scrub_personal_data(t) for t in report.recent_news_and_triggers
                ],
                "identified_pain_points": [
                    scrub_personal_data(p) for p in report.identified_pain_points
                ],
                "tech_stack": report.tech_stack.model_copy(
                    update={
                        "hiring_signals": [
                            scrub_personal_data(h) for h in report.tech_stack.hiring_signals
                        ],
                        "inferred_infrastructure_needs": scrub_personal_data(
                            report.tech_stack.inferred_infrastructure_needs
                        ),
                    }
                ),
                "outreach": report.outreach.model_copy(
                    update={
                        "subject_line": scrub_personal_data(report.outreach.subject_line),
                        "hyper_personalized_pitch": scrub_personal_data(
                            report.outreach.hyper_personalized_pitch
                        ),
                        "icebreaker_hook": scrub_personal_data(report.outreach.icebreaker_hook),
                        "call_to_action": scrub_personal_data(report.outreach.call_to_action),
                        "phone_call_bullet_points": [
                            scrub_personal_data(b)
                            for b in report.outreach.phone_call_bullet_points
                        ],
                        "art14_transparency_notice": art14_footer,
                        "advertising_compliance": adv_compliance,
                    }
                ),
                "created_at_utc": created_utc,
                "expires_at_utc": expires_utc,
                "pii_redacted": True,
            }
        )
    else:
        report = report.model_copy(
            update={
                "outreach": report.outreach.model_copy(
                    update={
                        "art14_transparency_notice": art14_footer,
                        "advertising_compliance": adv_compliance,
                    }
                ),
                "created_at_utc": created_utc,
                "expires_at_utc": expires_utc,
                "pii_redacted": False,
            }
        )

    # Ensure Output Guardrail validation passes
    postcheck = validate_lead_output(report, settings=settings)
    if not postcheck.is_valid:
        raise ValueError(postcheck.reason)

    # Fallback if SDK hooks did not populate records (e.g. mocked Runner in unit tests)
    if not run_context.agent_records:
        run_context.record_from_sdk_result(
            agent_name="Lead Orchestrator",
            role="Workflow Orchestration & Structuring",
            model=settings.reasoning_model,
            run_result=result,
            latency_seconds=elapsed,
        )

    return report, run_context
