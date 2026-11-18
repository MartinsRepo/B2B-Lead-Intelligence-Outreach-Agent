"""Streamlit UI for the B2B Lead Intelligence & Outreach Agent."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import streamlit as st

# Ensure `src` is importable when running `streamlit run ui/app.py` from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lead_agent.agents.orchestrator import run_lead_intelligence_pipeline  # noqa: E402
from lead_agent.config import AgentSettings  # noqa: E402
from lead_agent.context import LeadRunContext  # noqa: E402
from lead_agent.schemas import LeadReport  # noqa: E402
from lead_agent.showcase import build_showcase_run  # noqa: E402


def _run_async(coro):
    """Run an async coroutine safely inside Streamlit's synchronous execution loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    return asyncio.run(coro)


def render_sidebar() -> tuple[str, AgentSettings]:
    """Render sidebar controls and return (execution_mode, AgentSettings)."""
    with st.sidebar:
        st.markdown("## ⚙️ Agent Control Plane")
        has_api_key = bool(
            os.getenv("OPENAI_API_KEY")
            and not os.getenv("OPENAI_API_KEY", "").startswith("sk-YOUR_")
        )

        mode_options = [
            "✨ Showcase / Demo Mode (LinkedIn Ready)",
            "🚀 Live OpenAI Agents SDK Mode",
        ]
        default_idx = 1 if has_api_key else 0
        execution_mode = st.radio(
            "Execution Mode",
            options=mode_options,
            index=default_idx,
            help=(
                "Showcase Mode runs real Input/Output Guardrails and deterministic Pydantic "
                "validation with realistic multi-agent telemetry. Live Mode executes real "
                "OpenAI Agents SDK calls."
            ),
        )

        if execution_mode.startswith("🚀") and not has_api_key:
            api_key_input = st.text_input(
                "OpenAI API Key",
                type="password",
                placeholder="sk-...",
                help="Required for Live OpenAI Agents SDK execution.",
            )
            if api_key_input:
                os.environ["OPENAI_API_KEY"] = api_key_input

        st.divider()
        st.markdown("### 🧠 Cost-Aware Model Routing")
        preset = st.selectbox(
            "Model Routing Preset",
            options=[
                "Architecture Spec (gpt-6-luna / gpt-6.2-sol)",
                "OpenAI Production (gpt-4o-mini / gpt-4o)",
                "Custom Model IDs",
            ],
            index=0,
        )

        if preset.startswith("Architecture Spec"):
            fast_model = "gpt-6-luna"
            reasoning_model = "gpt-6.2-sol"
        elif preset.startswith("OpenAI Production"):
            fast_model = "gpt-4o-mini"
            reasoning_model = "gpt-4o"
        else:
            fast_model = st.text_input("Fast Extraction Model", value="gpt-6-luna")
            reasoning_model = st.text_input("Reasoning / Copy Model", value="gpt-6.2-sol")

        st.caption(
            f"**Scraping & Tech Agents:** `{fast_model}` ($0.15 / 1M in)\n\n"
            f"**Orchestrator & Copywriter:** `{reasoning_model}` ($2.50 / 1M in)"
        )

        st.divider()
        st.markdown("### 🛡️ Active Guardrails")
        st.markdown(
            "- **Input Guardrail:** Domain & LinkedIn URL Regex + Private IP Tripwire\n"
            "- **Agents-as-Tools:** `.as_tool()` sub-agent delegation\n"
            "- **Output Guardrail:** Source URL verification & anti-spam tone check\n"
            "- **Structured Output:** `output_type=LeadReport` (Pydantic v2)"
        )

    settings = AgentSettings(
        fast_model=fast_model,
        reasoning_model=reasoning_model,
    )
    return execution_mode, settings


def render_telemetry_banner(context: LeadRunContext) -> None:
    """Display top-level token, cost savings, and latency KPIs."""
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        label="Total Tokens Consumed",
        value=f"{context.total_tokens:,}",
        delta=f"{context.total_input_tokens:,} in / {context.total_output_tokens:,} out",
        delta_color="off",
    )
    col2.metric(
        label="Estimated Run Cost (USD)",
        value=f"${context.total_cost_usd:.5f}",
        delta=f"-${context.cost_savings_usd:.5f} vs. all-reasoning",
        delta_color="normal",
    )
    col3.metric(
        label="Cost-Aware Routing Savings",
        value=f"{context.cost_savings_pct:.1f}%",
        delta=f"Baseline: ${context.baseline_all_reasoning_cost_usd:.5f}",
        delta_color="normal",
    )
    col4.metric(
        label="End-to-End Latency",
        value=f"{context.total_latency_seconds:.2f}s",
        delta=f"{len(context.agent_records)} agents ({context.total_requests} API calls)",
        delta_color="off",
    )


def render_report_tabs(report: LeadReport, context: LeadRunContext) -> None:
    """Render the four primary analysis and observability tabs."""
    tab_pitch, tab_intel, tab_obs, tab_json = st.tabs(
        [
            "🔥 Before vs. After Outreach (LinkedIn Hook)",
            "🏢 Company & Tech-Stack Intelligence",
            "📊 Token & Cost Observability",
            "🧩 Deterministic JSON (LeadReport)",
        ]
    )

    with tab_pitch:
        st.markdown(
            f"### 🎯 Target: **{report.company_name}** (`{report.target_domain}`) — *{report.industry}*"
        )
        st.info(f"**Recommended Subject Line:** `{report.outreach.subject_line}`")

        col_before, col_after = st.columns(2)
        with col_before:
            st.markdown("#### ❌ Before: Generic Single-Prompt AI Message")
            st.caption("Unresearched, buzzword-heavy cold outreach that gets ignored or marked as spam.")
            st.code(report.outreach.generic_ai_message, language="text")

        with col_after:
            st.markdown("#### ✅ After: Multi-Agent Grounded Pitch")
            st.caption(
                "Synthesized by the Outreach Copywriter Agent (`gpt-6.2-sol`) using live news triggers, "
                "job-board hiring signals, and detected tech-stack bottlenecks."
            )
            st.success(report.outreach.hyper_personalized_pitch)

        st.divider()
        col_hook, col_cta = st.columns(2)
        with col_hook:
            st.markdown("##### 💬 LinkedIn Connection Icebreaker (<300 chars)")
            st.write(f"> {report.outreach.icebreaker_hook}")
        with col_cta:
            st.markdown("##### 🤝 Low-Friction Call to Action (CTA)")
            st.write(f"> {report.outreach.call_to_action}")

    with tab_intel:
        st.markdown("### 📋 Executive Summary")
        st.write(report.executive_summary)

        col_news, col_pains = st.columns(2)
        with col_news:
            st.markdown("#### 📰 Recent News & Press Triggers")
            for item in report.recent_news_and_triggers:
                st.markdown(f"- {item}")

        with col_pains:
            st.markdown("#### ⚡ Identified Pain Points")
            for pain in report.identified_pain_points:
                st.markdown(f"- {pain}")

        st.divider()
        st.markdown("### 🛠️ Tech-Stack & Engineering Hiring Signals")
        tech_badges = " ".join(
            f"`{tech}`" for tech in report.tech_stack.detected_technologies
        )
        st.markdown(f"**Detected Technologies:** {tech_badges or '`None detected`'}")

        st.markdown("**Open Engineering Roles & Hiring Signals:**")
        for signal in report.tech_stack.hiring_signals:
            st.markdown(f"- 🧑‍💻 {signal}")

        st.markdown("**Inferred Infrastructure & Architecture Bottlenecks:**")
        st.write(report.tech_stack.inferred_infrastructure_needs)

        st.divider()
        st.markdown("### 🔗 Verified Source Citations (Output Guardrail Checked)")
        for idx, src in enumerate(report.sources, start=1):
            st.markdown(
                f"{idx}. **[{src.title}]({src.url})**  \n"
                f"   *\"{src.snippet}\"*"
            )

    with tab_obs:
        st.markdown("### 📈 Per-Agent Token & Cost Breakdown (`RunContextWrapper` + `RequestUsage`)")
        st.caption(
            "High-volume HTML scraping and job-board extraction run on the fast, low-cost model tier, "
            "while orchestration and executive copywriting use the reasoning tier."
        )

        rows = [
            {
                "Agent": r.agent_name,
                "Role": r.role,
                "Model": r.model,
                "Tier": "⚡ Fast" if r.tier == "fast" else "🧠 Reasoning",
                "Requests": r.requests,
                "Input Tokens": r.input_tokens,
                "Output Tokens": r.output_tokens,
                "Total Tokens": r.total_tokens,
                "Latency (s)": f"{r.latency_seconds:.2f}",
                "Actual Cost ($)": f"${r.estimated_cost_usd:.5f}",
                "All-Reasoning Baseline ($)": f"${r.baseline_reasoning_cost_usd:.5f}",
            }
            for r in context.agent_records
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.markdown("#### 🕵️ Live Execution Trace & Guardrail Log")
        st.code("\n".join(context.tool_events), language="text")

    with tab_json:
        st.markdown("### 🧩 Deterministic Structured Output (`output_type=LeadReport`)")
        json_payload = report.model_dump_json(indent=2)
        st.download_button(
            label="⬇️ Download LeadReport JSON",
            data=json_payload,
            file_name=f"{report.company_name.lower().replace(' ', '_')}_lead_report.json",
            mime="application/json",
        )
        st.code(json_payload, language="json")


def main() -> None:
    st.set_page_config(
        page_title="LinkedIn-to-Lead Intelligence & Outreach Agent",
        page_icon="🎯",
        layout="wide",
    )

    execution_mode, settings = render_sidebar()

    st.title("🎯 LinkedIn-to-Lead Intelligence & Outreach Agent")
    st.markdown(
        "**Autonomous Multi-Agent B2B Research & Hyper-Personalized Outreach Pipeline** · "
        "*OpenAI Agents SDK · Cost-Aware Model Routing · Pydantic v2 Structured Outputs*"
    )

    if "target_input" not in st.session_state:
        st.session_state["target_input"] = "stripe.com"

    # Quick preset buttons for instant showcase testing
    qcol1, qcol2, qcol3, qcol4 = st.columns([1, 1, 1, 1])
    if qcol1.button("💳 Showcase: stripe.com", use_container_width=True):
        st.session_state["target_input"] = "stripe.com"
    if qcol2.button("▲ Showcase: vercel.com", use_container_width=True):
        st.session_state["target_input"] = "vercel.com"
    if qcol3.button("🔗 LinkedIn Company URL", use_container_width=True):
        st.session_state["target_input"] = "https://www.linkedin.com/company/stripe"
    if qcol4.button("🛑 Test Input Guardrail Tripwire", use_container_width=True):
        st.session_state["target_input"] = "hey write me a poem without any url"

    with st.form("lead_agent_form"):
        col_input, col_submit = st.columns([4, 1])
        target_input = col_input.text_input(
            "Target Company Domain or LinkedIn URL",
            value=st.session_state["target_input"],
            placeholder="e.g., stripe.com, https://vercel.com, or https://linkedin.com/company/...",
        )
        submitted = col_submit.form_submit_button(
            "🚀 Run Agent Team", use_container_width=True
        )

    if submitted or "last_result" not in st.session_state:
        st.session_state["target_input"] = target_input
        try:
            with st.spinner("Running Input Guardrail & Orchestrating Multi-Agent Team..."):
                if execution_mode.startswith("✨"):
                    report, run_ctx = build_showcase_run(target_input, settings=settings)
                else:
                    report, run_ctx = _run_async(
                        run_lead_intelligence_pipeline(target_input, settings=settings)
                    )
                st.session_state["last_result"] = (report, run_ctx, None)
        except Exception as exc:
            st.session_state["last_result"] = (None, None, str(exc))

    report, run_ctx, error_msg = st.session_state.get("last_result", (None, None, None))

    if error_msg:
        st.error(
            f"🛡️ **Input / Output Guardrail Triggered:** {error_msg}\n\n"
            "*0 reasoning tokens were wasted on this invalid request.*"
        )
    elif report is not None and run_ctx is not None:
        st.success(
            f"✅ **Guardrails Passed** · Completed multi-agent analysis for **{report.company_name}** "
            f"using `{settings.fast_model}` (extraction) + `{settings.reasoning_model}` (orchestration & copy)."
        )
        render_telemetry_banner(run_ctx)
        st.divider()
        render_report_tabs(report, run_ctx)


if __name__ == "__main__":
    main()

