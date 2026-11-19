"""Configuration and model routing settings for the B2B Lead Intelligence Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SPAM_PHRASES: tuple[str, ...] = (
    "guaranteed 10x",
    "act now before it's too late",
    "100% free money",
    "click here immediately",
)


@dataclass(frozen=True)
class ModelPricing:
    """Pricing per 1,000,000 tokens in USD."""

    input_per_1m: float
    output_per_1m: float

    def compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Compute total USD cost for the given input and output token counts."""
        input_cost = (max(input_tokens, 0) / 1_000_000) * self.input_per_1m
        output_cost = (max(output_tokens, 0) / 1_000_000) * self.output_per_1m
        return round(input_cost + output_cost, 6)


@dataclass
class AgentSettings:
    """Runtime settings for Cost-Aware Model Routing, Guardrails, and Sub-Agents."""

    fast_model: str = field(
        default_factory=lambda: os.getenv("FAST_MODEL", "gpt-6-luna")
    )
    reasoning_model: str = field(
        default_factory=lambda: os.getenv("REASONING_MODEL", "gpt-6.2-sol")
    )
    fast_pricing: ModelPricing = field(
        default_factory=lambda: ModelPricing(
            input_per_1m=float(os.getenv("FAST_MODEL_INPUT_COST_PER_1M", "0.15")),
            output_per_1m=float(os.getenv("FAST_MODEL_OUTPUT_COST_PER_1M", "0.60")),
        )
    )
    reasoning_pricing: ModelPricing = field(
        default_factory=lambda: ModelPricing(
            input_per_1m=float(os.getenv("REASONING_MODEL_INPUT_COST_PER_1M", "2.50")),
            output_per_1m=float(os.getenv("REASONING_MODEL_OUTPUT_COST_PER_1M", "10.00")),
        )
    )
    http_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_SECONDS", "15.0"))
    )
    max_scrape_chars: int = field(
        default_factory=lambda: int(os.getenv("MAX_SCRAPE_CHARS", "6000"))
    )

    # 1. Input Guardrail Configuration
    enable_input_guardrail: bool = True
    block_private_ips: bool = True

    # 2. Agents-as-Tools (.as_tool()) Delegation Configuration
    enable_company_news_agent: bool = True
    enable_tech_stack_agent: bool = True
    enable_copywriter_agent: bool = True

    # 3. Output Guardrail Configuration
    enable_output_guardrail: bool = True
    min_sources_required: int = 1
    min_source_credibility: float = 0.50
    min_pitch_length: int = 40
    enable_anti_spam_check: bool = True
    blocked_spam_phrases: tuple[str, ...] = DEFAULT_SPAM_PHRASES

    # 4. Structured Output Configuration
    enforce_structured_output: bool = True

    def get_pricing_for_model(self, model_name: str) -> ModelPricing:
        """Return the pricing tier matching a given model name."""
        normalized = model_name.lower().strip()
        if (
            normalized == self.fast_model.lower()
            or "luna" in normalized
            or "mini" in normalized
            or "nano" in normalized
        ):
            return self.fast_pricing
        return self.reasoning_pricing


DEFAULT_SETTINGS = AgentSettings()
