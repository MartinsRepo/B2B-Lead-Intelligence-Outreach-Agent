"""Real-time token and cost observability context for the OpenAI Agents SDK."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from lead_agent.config import DEFAULT_SETTINGS, AgentSettings


@dataclass
class AgentUsageRecord:
    """Token, latency, and cost telemetry for a single agent execution."""

    agent_name: str
    role: str
    model: str
    tier: str  # "fast" or "reasoning"
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
    baseline_reasoning_cost_usd: float = 0.0


@dataclass
class LeadRunContext:
    """Shared context object wrapped by RunContextWrapper[LeadRunContext].

    Tracks per-agent RequestUsage, latency, and cost savings from Cost-Aware Routing.
    """

    target_input: str
    settings: AgentSettings = field(default_factory=lambda: DEFAULT_SETTINGS)
    agent_records: list[AgentUsageRecord] = field(default_factory=list)
    tool_events: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)

    def log_tool_event(self, message: str) -> None:
        """Append a human-readable trace event for live UI observability."""
        elapsed = time.perf_counter() - self.started_at
        self.tool_events.append(f"[{elapsed:05.2f}s] {message}")

    def record_agent_usage(
        self,
        agent_name: str,
        role: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        requests: int = 1,
        latency_seconds: float = 0.0,
    ) -> AgentUsageRecord:
        """Record token usage and calculate actual vs. all-reasoning baseline cost."""
        pricing = self.settings.get_pricing_for_model(model)
        is_fast = pricing == self.settings.fast_pricing
        tier = "fast" if is_fast else "reasoning"

        total_tokens = input_tokens + output_tokens
        actual_cost = pricing.compute_cost(input_tokens, output_tokens)
        baseline_cost = self.settings.reasoning_pricing.compute_cost(
            input_tokens, output_tokens
        )

        record = AgentUsageRecord(
            agent_name=agent_name,
            role=role,
            model=model,
            tier=tier,
            requests=requests,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_seconds=round(latency_seconds, 2),
            estimated_cost_usd=actual_cost,
            baseline_reasoning_cost_usd=baseline_cost,
        )
        self.agent_records.append(record)
        return record

    def record_from_sdk_result(
        self,
        agent_name: str,
        role: str,
        model: str,
        run_result: Any,
        latency_seconds: float = 0.0,
    ) -> AgentUsageRecord:
        """Extract RequestUsage from an OpenAI Agents SDK RunResult and record telemetry."""
        input_tokens = 0
        output_tokens = 0
        requests = 0

        raw_responses = getattr(run_result, "raw_responses", None) or []
        for resp in raw_responses:
            usage = getattr(resp, "usage", None)
            if usage is not None:
                input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
                requests += int(getattr(usage, "requests", 1) or 1)

        context_wrapper = getattr(run_result, "context_wrapper", None)
        if input_tokens == 0 and output_tokens == 0 and context_wrapper is not None:
            usage = getattr(context_wrapper, "usage", None)
            if usage is not None:
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                requests = int(getattr(usage, "requests", 1) or 1)

        return self.record_agent_usage(
            agent_name=agent_name,
            role=role,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requests=max(requests, 1),
            latency_seconds=latency_seconds,
        )

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.agent_records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.agent_records)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.agent_records)

    @property
    def total_requests(self) -> int:
        return sum(r.requests for r in self.agent_records)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(r.estimated_cost_usd for r in self.agent_records), 6)

    @property
    def baseline_all_reasoning_cost_usd(self) -> float:
        return round(sum(r.baseline_reasoning_cost_usd for r in self.agent_records), 6)

    @property
    def cost_savings_usd(self) -> float:
        return round(
            max(0.0, self.baseline_all_reasoning_cost_usd - self.total_cost_usd), 6
        )

    @property
    def cost_savings_pct(self) -> float:
        baseline = self.baseline_all_reasoning_cost_usd
        if baseline <= 0:
            return 0.0
        return round((self.cost_savings_usd / baseline) * 100.0, 1)

    @property
    def total_latency_seconds(self) -> float:
        if self.agent_records:
            return round(sum(r.latency_seconds for r in self.agent_records), 2)
        return round(time.perf_counter() - self.started_at, 2)

