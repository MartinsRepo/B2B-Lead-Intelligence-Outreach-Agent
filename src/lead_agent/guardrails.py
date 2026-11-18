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


from lead_agent.context import LeadRunContext
from lead_agent.schemas import LeadReport

# Matches valid domains (e.g. stripe.com, sub.acme.co.uk) or full HTTP/HTTPS URLs
DOMAIN_REGEX = re.compile(
    r"^(?:https?://)?(?:www\.)?([a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,24}(?:/[^\s]*)?$"
)
LINKEDIN_REGEX = re.compile(
    r"^(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in|school)/[a-zA-Z0-9_-]+/?",
    re.IGNORECASE,
)
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

SPAM_CLICHES = (
    "guaranteed 10x",
    "act now before it's too late",
    "100% free money",
    "click here immediately",
)


@dataclass(frozen=True)
class ValidationOutcome:
    """Deterministic validation result used by guardrails and UI pre-checks."""

    is_valid: bool
    normalized_target: str
    reason: str


def validate_lead_input(raw_input: str) -> ValidationOutcome:
    """Validate that user input contains a legitimate B2B domain or LinkedIn profile/company URL."""
    cleaned = raw_input.strip()
    if not cleaned:
        return ValidationOutcome(
            is_valid=False,
            normalized_target="",
            reason="Input is empty. Please provide a valid company domain (e.g., 'stripe.com') or LinkedIn URL.",
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
        if DOMAIN_REGEX.match(stripped_token) or LINKEDIN_REGEX.match(stripped_token):
            candidate = stripped_token
            break

    if not (DOMAIN_REGEX.match(candidate) or LINKEDIN_REGEX.match(candidate)):
        return ValidationOutcome(
            is_valid=False,
            normalized_target="",
            reason=(
                f"'{cleaned}' is not a valid company domain or LinkedIn URL. "
                "Examples: 'stripe.com', 'https://vercel.com', or 'https://linkedin.com/company/openai'."
            ),
        )

    normalized = (
        candidate
        if candidate.startswith(("http://", "https://"))
        else f"https://{candidate}"
    )
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()

    if hostname in BLOCKED_HOSTS or hostname.endswith(".local") or hostname.endswith(".internal"):
        return ValidationOutcome(
            is_valid=False,
            normalized_target="",
            reason=f"Host '{hostname}' is a private/local address and is blocked by the Input Guardrail.",
        )

    return ValidationOutcome(
        is_valid=True,
        normalized_target=normalized,
        reason="Valid B2B domain or LinkedIn URL.",
    )


def validate_lead_output(report: LeadReport) -> ValidationOutcome:
    """Verify that the generated LeadReport has valid source citations, grounded claims, and professional tone."""
    if not report.sources:
        return ValidationOutcome(
            is_valid=False,
            normalized_target=report.target_domain,
            reason="Output Guardrail failed: LeadReport must include at least one verified source citation.",
        )

    for src in report.sources:
        if not src.url.startswith(("http://", "https://")):
            return ValidationOutcome(
                is_valid=False,
                normalized_target=report.target_domain,
                reason=f"Output Guardrail failed: Invalid source URL '{src.url}'.",
            )

    pitch_text = report.outreach.hyper_personalized_pitch.strip()
    if len(pitch_text) < 40:
        return ValidationOutcome(
            is_valid=False,
            normalized_target=report.target_domain,
            reason="Output Guardrail failed: Personalized outreach pitch is too short (<40 chars).",
        )

    lower_pitch = pitch_text.lower()
    for cliche in SPAM_CLICHES:
        if cliche in lower_pitch:
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

    outcome = validate_lead_input(raw_text)
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
    outcome = validate_lead_output(output)
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        status = "PASSED" if outcome.is_valid else f"BLOCKED ({outcome.reason})"
        ctx.context.log_tool_event(f"Output Guardrail -> {status}")

    return GuardrailFunctionOutput(
        output_info={"reason": outcome.reason},
        tripwire_triggered=not outcome.is_valid,
    )

