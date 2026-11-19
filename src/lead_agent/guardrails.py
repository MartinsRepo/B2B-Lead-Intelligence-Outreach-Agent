"""Input and Output Guardrails for the B2B Lead Intelligence & Outreach Agent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

try:
    from agents import (
        Agent,
        GuardrailFunctionOutput,
        RunContextWrapper,
        TResponseInputItem,
        input_guardrail,
        output_guardrail,
    )
except ImportError:  # pragma: no cover
    Agent = Any  # type: ignore[misc,assignment]
    RunContextWrapper = Any  # type: ignore[misc,assignment]
    TResponseInputItem = Any  # type: ignore[misc,assignment]

    @dataclass
    class GuardrailFunctionOutput:  # type: ignore[no-redef]
        output_info: Any
        tripwire_triggered: bool

    def input_guardrail(func=None, **_kwargs):  # type: ignore[no-redef]
        if func is None:
            return lambda f: f
        return func

    def output_guardrail(func=None, **_kwargs):  # type: ignore[no-redef]
        if func is None:
            return lambda f: f
        return func


from lead_agent.config import DEFAULT_SETTINGS, DEFAULT_SPAM_PHRASES, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.schemas import LeadReport

# Matches valid domains (e.g. stripe.com, sub.acme.co.uk) or full HTTP/HTTPS URLs
DOMAIN_REGEX = re.compile(
    r"^(?:https?://)?(?:www\.)?([a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,24}(?::\d{1,5})?(?:/[^\s]*)?$"
)
LOCAL_OR_IP_REGEX = re.compile(
    r"^(?:https?://)?(?:localhost|\d{1,3}(?:\.\d{1,3}){3})(?::\d{1,5})?(?:/[^\s]*)?$",
    re.IGNORECASE,
)
LINKEDIN_REGEX = re.compile(
    r"^(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in|school)/[a-zA-Z0-9_-]+/?",
    re.IGNORECASE,
)
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

SPAM_CLICHES = DEFAULT_SPAM_PHRASES


@dataclass(frozen=True)
class ValidationOutcome:
    """Deterministic validation result used by guardrails and UI pre-checks."""

    is_valid: bool
    normalized_target: str
    reason: str


def validate_lead_input(
    raw_input: str,
    settings: AgentSettings | None = None,
) -> ValidationOutcome:
    """Validate that user input contains a legitimate B2B domain or corporate URL."""
    active_settings = settings or DEFAULT_SETTINGS
    cleaned = raw_input.strip()
    if not cleaned:
        return ValidationOutcome(
            is_valid=False,
            normalized_target="",
            reason="Input is empty. Please provide a valid company domain (e.g., 'stripe.com') or corporate URL.",
        )

    if not active_settings.enable_input_guardrail:
        normalized_bypass = (
            cleaned
            if cleaned.startswith(("http://", "https://"))
            else f"https://{cleaned}"
        )
        return ValidationOutcome(
            is_valid=True,
            normalized_target=normalized_bypass,
            reason="Input Guardrail disabled by configuration.",
        )

    if len(cleaned) > 300:
        return ValidationOutcome(
            is_valid=False,
            normalized_target="",
            reason="Input exceeds maximum URL/domain length (300 characters).",
        )

    # Extract first URL or domain token if user typed a short phrase like "Analyze stripe.com"
    tokens = cleaned.split()
    candidate = cleaned
    for token in tokens:
        stripped_token = token.strip(",;()[]\"'")
        if (
            DOMAIN_REGEX.match(stripped_token)
            or LINKEDIN_REGEX.match(stripped_token)
            or LOCAL_OR_IP_REGEX.match(stripped_token)
        ):
            candidate = stripped_token
            break

    is_domain_or_linkedin = bool(
        DOMAIN_REGEX.match(candidate) or LINKEDIN_REGEX.match(candidate)
    )
    is_local_or_ip = bool(LOCAL_OR_IP_REGEX.match(candidate))

    if not (is_domain_or_linkedin or is_local_or_ip):
        return ValidationOutcome(
            is_valid=False,
            normalized_target="",
            reason=(
                f"'{cleaned}' is not a valid company domain or corporate URL. "
                "Examples: 'stripe.com', 'https://vercel.com', or 'https://bmwgroup.com/en'."
            ),
        )

    normalized = (
        candidate
        if candidate.startswith(("http://", "https://"))
        else f"https://{candidate}"
    )
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()

    if active_settings.block_private_ips and (
        is_local_or_ip
        or hostname in BLOCKED_HOSTS
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
    ):
        return ValidationOutcome(
            is_valid=False,
            normalized_target="",
            reason=f"Host '{hostname}' is a private/local address and is blocked by the Input Guardrail.",
        )

    return ValidationOutcome(
        is_valid=True,
        normalized_target=normalized,
        reason="Valid B2B domain or corporate URL.",
    )


def validate_lead_output(
    report: LeadReport,
    settings: AgentSettings | None = None,
) -> ValidationOutcome:
    """Verify that the generated LeadReport has valid source citations, grounded claims, and professional tone."""
    active_settings = settings or DEFAULT_SETTINGS
    if not active_settings.enable_output_guardrail:
        return ValidationOutcome(
            is_valid=True,
            normalized_target=report.target_domain,
            reason="Output Guardrail disabled by configuration.",
        )

    min_sources = max(0, active_settings.min_sources_required)
    if len(report.sources) < min_sources:
        return ValidationOutcome(
            is_valid=False,
            normalized_target=report.target_domain,
            reason=(
                f"Output Guardrail failed: LeadReport must include at least {min_sources} "
                f"verified source citation(s), got {len(report.sources)}."
            ),
        )

    for src in report.sources:
        if not src.url.startswith(("http://", "https://")):
            return ValidationOutcome(
                is_valid=False,
                normalized_target=report.target_domain,
                reason=f"Output Guardrail failed: Invalid source URL '{src.url}'.",
            )
        if src.composite_score < active_settings.min_source_credibility:
            return ValidationOutcome(
                is_valid=False,
                normalized_target=report.target_domain,
                reason=(
                    f"Output Guardrail failed: Source '{src.url}' quality score "
                    f"({src.composite_score:.2f}) is below minimum threshold "
                    f"({active_settings.min_source_credibility:.2f})."
                ),
            )

    pitch_text = report.outreach.hyper_personalized_pitch.strip()
    min_len = max(1, active_settings.min_pitch_length)
    if len(pitch_text) < min_len:
        return ValidationOutcome(
            is_valid=False,
            normalized_target=report.target_domain,
            reason=f"Output Guardrail failed: Personalized outreach pitch is too short (<{min_len} chars).",
        )

    if active_settings.enable_anti_spam_check:
        lower_pitch = pitch_text.lower()
        for cliche in active_settings.blocked_spam_phrases:
            cleaned_cliche = cliche.strip().lower()
            if cleaned_cliche and cleaned_cliche in lower_pitch:
                return ValidationOutcome(
                    is_valid=False,
                    normalized_target=report.target_domain,
                    reason=f"Output Guardrail failed: Outreach pitch contains prohibited spam phrase '{cliche}'.",
                )

    return ValidationOutcome(
        is_valid=True,
        normalized_target=report.target_domain,
        reason="LeadReport passed all factual grounding and tone checks.",
    )


@input_guardrail(name="validate_b2b_domain_or_linkedin_url")
async def validate_lead_input_guardrail(
    ctx: RunContextWrapper[LeadRunContext],
    agent: Agent[LeadRunContext],
    input_data: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:
    """OpenAI Agents SDK Input Guardrail preventing token spend on malformed inputs."""
    if isinstance(input_data, str):
        raw_text = input_data
    else:
        parts: list[str] = []
        for item in input_data:
            if isinstance(item, dict) and "content" in item:
                parts.append(str(item["content"]))
            else:
                parts.append(str(item))
        raw_text = " ".join(parts)

    active_settings = (
        ctx.context.settings
        if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext)
        else DEFAULT_SETTINGS
    )
    outcome = validate_lead_input(raw_text, settings=active_settings)
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        status = "PASSED" if outcome.is_valid else f"BLOCKED ({outcome.reason})"
        ctx.context.log_tool_event(f"Input Guardrail -> {status}")

    return GuardrailFunctionOutput(
        output_info={"reason": outcome.reason, "normalized_target": outcome.normalized_target},
        tripwire_triggered=not outcome.is_valid,
    )


@output_guardrail(name="validate_lead_report_sources_and_tone")
async def validate_lead_output_guardrail(
    ctx: RunContextWrapper[LeadRunContext],
    agent: Agent[LeadRunContext],
    output: LeadReport,
) -> GuardrailFunctionOutput:
    """OpenAI Agents SDK Output Guardrail enforcing source grounding and tone quality."""
    active_settings = (
        ctx.context.settings
        if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext)
        else DEFAULT_SETTINGS
    )
    outcome = validate_lead_output(output, settings=active_settings)
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        status = "PASSED" if outcome.is_valid else f"BLOCKED ({outcome.reason})"
        ctx.context.log_tool_event(f"Output Guardrail -> {status}")

    return GuardrailFunctionOutput(
        output_info={"reason": outcome.reason},
        tripwire_triggered=not outcome.is_valid,
    )
