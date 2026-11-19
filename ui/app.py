"""Streamlit UI for the B2B Lead Intelligence & Outreach Agent."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path

import streamlit as st

# Ensure `src` is importable when running `streamlit run ui/app.py` from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lead_agent.agents.orchestrator import run_lead_intelligence_pipeline  # noqa: E402
from lead_agent.config import DEFAULT_SPAM_PHRASES, AgentSettings  # noqa: E402
from lead_agent.context import LeadRunContext  # noqa: E402
from lead_agent.schemas import LeadReport  # noqa: E402


@st.cache_resource
def _get_background_event_loop() -> asyncio.AbstractEventLoop:
    """Create a persistent background event loop running in its own daemon thread.

    This avoids conflicts with Streamlit/Uvicorn's thread event loop and keeps the
    OpenAI Agents SDK's internal AsyncOpenAI/HTTPX client bound to a single open loop.
    """
    loop = asyncio.new_event_loop()

    def _run_loop(event_loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(event_loop)
        event_loop.run_forever()

    thread = threading.Thread(
        target=_run_loop, args=(loop,), name="lead-agent-async-loop", daemon=True
    )
    thread.start()
    return loop


def _run_async(coro):
    """Submit a coroutine to the persistent background event loop and wait for its result."""
    try:
        loop = _get_background_event_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    except Exception:
        coro.close()
        raise


def inject_custom_css() -> None:
    """Inject subtle CSS so the telemetry card matches the rounded, divided layout."""
    st.markdown(
        """
        <style>
        /* Add vertical dividers between metrics inside the telemetry container */
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:not(:first-child) div[data-testid="stMetric"] {
            border-left: 1px solid rgba(250, 250, 250, 0.18);
            padding-left: 1.1rem;
        }
        .hero-subtitle {
            font-size: 1.28rem;
            font-weight: 600;
            color: #f8fafc;
            margin-top: -0.35rem;
            margin-bottom: 0.35rem;
        }
        .hero-description {
            font-size: 1.06rem;
            line-height: 1.58;
            color: rgba(241, 245, 249, 0.84);
            margin-bottom: 1.15rem;
            max-width: 1180px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> AgentSettings:
    """Render sidebar controls and return configured AgentSettings."""
    with st.sidebar:
        st.markdown("## ⚙️ Agent Control Plane")
        has_api_key = bool(
            os.getenv("OPENAI_API_KEY")
            and not os.getenv("OPENAI_API_KEY", "").startswith("sk-YOUR_")
        )

        if not has_api_key:
            api_key_input = st.text_input(
                "OpenAI API Key",
                type="password",
                placeholder="sk-...",
                help="Required for OpenAI Agents SDK execution.",
            )
            if api_key_input:
                os.environ["OPENAI_API_KEY"] = api_key_input

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

        enable_input_guardrail = st.toggle(
            "Input Guardrail (Domain & URL Regex)",
            value=True,
            help="Validates corporate domains/URLs before any LLM tokens are spent.",
        )
        enable_output_guardrail = st.toggle(
            "Output Guardrail (Sources & Tone)",
            value=True,
            help="Verifies HTTP/HTTPS source citations, minimum pitch length, and anti-spam tone.",
        )
        enforce_structured_output = st.toggle(
            "Structured Output (LeadReport Schema)",
            value=True,
            disabled=True,
            help="Enforces strict Pydantic v2 output_type=LeadReport JSON validation.",
        )

        with st.expander("⚙️ Configure Guardrail & Tool Rules", expanded=False):
            st.markdown("**1. Input Guardrail Policy**")
            block_private_ips = st.checkbox(
                "Block Private & Localhost IPs (SSRF Tripwire)",
                value=True,
                disabled=not enable_input_guardrail,
            )

            st.markdown("**2. Agents-as-Tools (`.as_tool()`) Delegation**")
            enable_company_news_agent = st.checkbox(
                "Company & News Sub-Agent",
                value=True,
            )
            enable_tech_stack_agent = st.checkbox(
                "Tech-Stack & Job-Board Sub-Agent",
                value=True,
            )
            enable_copywriter_agent = st.checkbox(
                "Outreach Copywriter Sub-Agent",
                value=True,
            )

            st.markdown("**3. Output Guardrail Thresholds**")
            min_sources_required = st.number_input(
                "Min. Verified Source Citations",
                min_value=0,
                max_value=5,
                value=1,
                step=1,
                disabled=not enable_output_guardrail,
            )
            min_source_credibility = st.slider(
                "Min. Source Quality Score",
                min_value=0.0,
                max_value=0.95,
                value=0.50,
                step=0.05,
                disabled=not enable_output_guardrail,
                help="Rejects reports containing low-credibility or off-topic source citations.",
            )
            min_pitch_length = st.slider(
                "Min. Pitch Length (chars)",
                min_value=20,
                max_value=250,
                value=40,
                step=10,
                disabled=not enable_output_guardrail,
            )
            enable_anti_spam_check = st.checkbox(
                "Enable Anti-Spam Phrase Filter",
                value=True,
                disabled=not enable_output_guardrail,
            )
            raw_phrases = st.text_area(
                "Blocked Spam Phrases (comma-separated)",
                value=", ".join(DEFAULT_SPAM_PHRASES),
                disabled=not (enable_output_guardrail and enable_anti_spam_check),
                height=80,
            )
            blocked_phrases = tuple(
                p.strip() for p in raw_phrases.split(",") if p.strip()
            )

    return AgentSettings(
        fast_model=fast_model,
        reasoning_model=reasoning_model,
        enable_input_guardrail=enable_input_guardrail,
        block_private_ips=block_private_ips,
        enable_company_news_agent=enable_company_news_agent,
        enable_tech_stack_agent=enable_tech_stack_agent,
        enable_copywriter_agent=enable_copywriter_agent,
        enable_output_guardrail=enable_output_guardrail,
        min_sources_required=int(min_sources_required),
        min_source_credibility=float(min_source_credibility),
        min_pitch_length=int(min_pitch_length),
        enable_anti_spam_check=enable_anti_spam_check,
        blocked_spam_phrases=blocked_phrases or DEFAULT_SPAM_PHRASES,
        enforce_structured_output=enforce_structured_output,
    )


def render_telemetry_card(context: LeadRunContext | None) -> None:
    """Display the 4-column token, cost savings, and latency KPI card."""
    with st.container(border=True):
        col1, col2, col3, col4 = st.columns(4)
        if context is not None:
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
                delta_color="inverse",
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
        else:
            col1.metric(
                label="Total Tokens Consumed",
                value="—",
                delta="0 in / 0 out",
                delta_color="off",
            )
            col2.metric(
                label="Estimated Run Cost (USD)",
                value="$0.00000",
                delta="Awaiting agent run",
                delta_color="off",
            )
            col3.metric(
                label="Cost-Aware Routing Savings",
                value="0.0%",
                delta="Baseline: $0.00000",
                delta_color="off",
            )
            col4.metric(
                label="End-to-End Latency",
                value="0.00s",
                delta="4 agents ready",
                delta_color="off",
            )


def render_report_tabs(report: LeadReport, context: LeadRunContext) -> None:
    """Render the four primary analysis and observability tabs."""
    tab_pitch, tab_intel, tab_obs, tab_json = st.tabs(
        [
            "🔥 Outreach Synthesis (Baseline vs. Multi-Agent)",
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
            st.markdown("#### ❌ Standard Single-Prompt Baseline")
            st.caption("Unresearched, generic cold outreach without live press or tech-stack grounding.")
            st.code(report.outreach.generic_ai_message, language="text")

        with col_after:
            st.markdown("#### ✅ Multi-Agent Grounded Outreach Pitch")
            st.caption(
                "Synthesized by the Outreach Copywriter Agent (`gpt-6.2-sol`) using live news triggers, "
                "job-board hiring signals, and detected tech-stack bottlenecks."
            )
            st.success(report.outreach.hyper_personalized_pitch)

        st.divider()
        col_hook, col_cta = st.columns(2)
        with col_hook:
            st.markdown("##### 💬 Direct Message / Short-Form Icebreaker (<300 chars)")
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
        st.markdown("### 🔗 Verified & Scored Source Citations (Multi-Source Evaluation)")
        for idx, src in enumerate(report.sources, start=1):
            date_tag = f" · 📅 `{src.published_date}`" if src.published_date else ""
            st.markdown(
                f"{idx}. **[{src.title}]({src.url})**  \n"
                f"   🏷️ `{src.source_type}`{date_tag} · "
                f"⭐ **Quality Score:** `{src.composite_score:.2f}` "
                f"*(Credibility: `{src.credibility_score:.2f}` · Relevance: `{src.relevance_score:.2f}`)*  \n"
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
        st.dataframe(rows, width="stretch", hide_index=True)

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
        page_title="B2B Lead Intelligence & Outreach Agent",
        page_icon="🎯",
        layout="wide",
    )
    inject_custom_css()

    settings = render_sidebar()

    st.title("🎯 B2B Lead Intelligence & Outreach Agent")
    st.markdown(
        """
        <div class="hero-subtitle">
            Autonomous Multi-Agent B2B Research &amp; Hyper-Personalized Outreach Pipeline
        </div>
        <div class="hero-description">
            Enter a target company domain or corporate URL below to launch a coordinated team of specialized AI agents.
            The pipeline automatically validates your target via <strong>Input Guardrails</strong>, scrapes live press releases
            and news triggers, fingerprints the company's <strong>web &amp; cloud tech stack</strong>, analyzes open engineering
            roles for hiring signals, and synthesizes a <strong>source-verified executive outreach pitch</strong>—while
            tracking real-time token usage and cost savings from <strong>Cost-Aware Model Routing</strong>.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "target_input" not in st.session_state:
        st.session_state["target_input"] = ""

    # Top row: Left = Target Domain Form Card, Right = 4-Column Telemetry Card
    col_form, col_telemetry = st.columns([4, 7], gap="medium")

    with col_form:
        with st.form("lead_agent_form", border=True):
            target_input = st.text_input(
                "Target Company Domain or Corporate URL",
                value=st.session_state["target_input"],
                placeholder="e.g., bmwgroup.com/en, stripe.com, or https://vercel.com",
            )
            _, btn_col, _ = st.columns([1, 2, 1])
            submitted = btn_col.form_submit_button(
                "🚀 Run Agent Team", width="stretch"
            )

    if submitted:
        st.session_state["target_input"] = target_input
        try:
            with st.spinner("Running Input Guardrail & Orchestrating Multi-Agent Team..."):
                report, run_ctx = _run_async(
                    run_lead_intelligence_pipeline(target_input, settings=settings)
                )
                st.session_state["last_result"] = (report, run_ctx, None, None)
        except ValueError as guardrail_exc:
            st.session_state["last_result"] = (None, None, str(guardrail_exc), None)
        except Exception as api_exc:
            st.session_state["last_result"] = (None, None, None, str(api_exc))

    report, run_ctx, guardrail_error, api_error = st.session_state.get(
        "last_result", (None, None, None, None)
    )

    with col_telemetry:
        render_telemetry_card(run_ctx)

    if guardrail_error:
        st.error(
            f"🛡️ **Input / Output Guardrail Triggered:** {guardrail_error}\n\n"
            "*0 reasoning tokens were wasted on this invalid request.*"
        )
    elif api_error:
        st.error(f"⚠️ **Execution Error:** `{api_error}`")
    elif report is not None and run_ctx is not None:
        st.success(
            f"✅ **Guardrails Passed** · Completed multi-agent analysis for **{report.company_name}** "
            f"using `{settings.fast_model}` (extraction) + `{settings.reasoning_model}` (orchestration & copy)."
        )
        render_report_tabs(report, run_ctx)


if __name__ == "__main__":
    main()
