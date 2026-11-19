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

from lead_agent.agents.orchestrator import (  # noqa: E402
    resolve_live_model_name,
    run_lead_intelligence_pipeline,
)
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

        fast_model_options = [
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "o4-mini",
            "gpt-6-luna",
        ]
        reasoning_model_options = [
            "gpt-4o",
            "gpt-4.1",
            "o3-mini",
            "o3",
            "gpt-6.2-sol",
        ]

        env_fast = resolve_live_model_name(os.getenv("FAST_MODEL", "gpt-4o-mini"))
        env_reasoning = resolve_live_model_name(os.getenv("REASONING_MODEL", "gpt-4o"))

        default_fast_idx = (
            fast_model_options.index(env_fast) if env_fast in fast_model_options else 0
        )
        default_reasoning_idx = (
            reasoning_model_options.index(env_reasoning)
            if env_reasoning in reasoning_model_options
            else 0
        )

        fast_model = st.selectbox(
            "⚡ Fast Extraction Model",
            options=fast_model_options,
            index=default_fast_idx,
            help="Used by high-volume web scraping and HTML/job-board parsing sub-agents.",
        )
        reasoning_model = st.selectbox(
            "🧠 Reasoning & Copywriter Model",
            options=reasoning_model_options,
            index=default_reasoning_idx,
            help="Used by the Lead Orchestrator and Outreach Copywriter sub-agent.",
        )

        active_fast = resolve_live_model_name(fast_model)
        active_reasoning = resolve_live_model_name(reasoning_model)

        st.markdown(
            "**Active Agent Models in Use:**\n"
            f"- **Company & News Agent:** `{active_fast}` *($0.15 / 1M in)*\n"
            f"- **Tech-Stack Agent:** `{active_fast}` *($0.15 / 1M in)*\n"
            f"- **Outreach Copywriter:** `{active_reasoning}` *($2.50 / 1M in)*\n"
            f"- **Lead Orchestrator:** `{active_reasoning}` *($2.50 / 1M in)*"
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

            st.markdown("**4. 5-Step Source Fact-Checking**")
            enable_fact_checking = st.checkbox(
                "Re-Fetch Sources & Verify Claims Against Original Text",
                value=True,
                help=(
                    "1. Links each claim to a source URL  "
                    "2. Re-fetches the source  "
                    "3. Extracts the matching text passage  "
                    "4. Compares claim vs. original passage  "
                    "5. Marks unverified claims as hypothesis or discards them."
                ),
            )
            min_grounding_score = st.slider(
                "Min. Claim Grounding Score",
                min_value=0.10,
                max_value=0.75,
                value=0.25,
                step=0.05,
                disabled=not enable_fact_checking,
                help="Minimum lexical/entity overlap required to consider a claim grounded in the source text.",
            )
            policy_label = st.radio(
                "Unverified Claim Handling",
                options=[
                    "Mark as Hypothesis ([Hypothesis / Inferred])",
                    "Discard Unverified Claims",
                ],
                index=0,
                disabled=not enable_fact_checking,
            )
            unverified_claim_policy = (
                "discard" if policy_label.startswith("Discard") else "mark_as_hypothesis"
            )

    return AgentSettings(
        fast_model=active_fast,
        reasoning_model=active_reasoning,
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
        enable_fact_checking=enable_fact_checking,
        min_grounding_score=float(min_grounding_score),
        unverified_claim_policy=unverified_claim_policy,
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
            "🔥 Outreach & Phone Call Brief",
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

        col_left, col_right = st.columns([6, 5], gap="large")
        with col_left:
            st.markdown("#### ✅ Multi-Agent Grounded Outreach Pitch")
            st.caption(
                f"Synthesized by the Outreach Copywriter Agent (`{context.settings.reasoning_model}`) using verified news triggers, "
                "job-board hiring signals, and detected tech-stack bottlenecks."
            )
            st.success(report.outreach.hyper_personalized_pitch)

        with col_right:
            with st.container(border=True):
                st.markdown("##### 💬 Direct Message / Short-Form Icebreaker (<300 chars)")
                st.write(f"> {report.outreach.icebreaker_hook}")

            with st.container(border=True):
                st.markdown("##### 🤝 Low-Friction Call to Action (CTA)")
                st.write(f"> {report.outreach.call_to_action}")

        st.divider()
        with st.container(border=True):
            st.markdown("#### 📞 Short Phone Call Memory Notices (Quick Call Cheat-Sheet)")
            st.caption(
                "Key talking points, tech-stack cues, and discovery prompts to keep in front of you during a live call."
            )
            if report.outreach.phone_call_bullet_points:
                for bullet in report.outreach.phone_call_bullet_points:
                    st.markdown(f"- {bullet}")
            else:
                st.markdown(
                    f"- **Opening Trigger:** Reference *{report.recent_news_and_triggers[0]}*\n"
                    f"- **Pain-Point Hypothesis:** Validate *{report.identified_pain_points[0]}*\n"
                    f"- **Tech-Stack Context:** Mention `{', '.join(report.tech_stack.detected_technologies[:4]) or 'core stack'}`\n"
                    f"- **Next-Step Close:** {report.outreach.call_to_action}"
                )

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

        if report.tech_stack.technology_signals:
            confirmed_techs = [
                f"`{t.name} ({int(t.confidence_score * 100)}%)`"
                for t in report.tech_stack.technology_signals
                if t.detection_status == "confirmed"
            ]
            suspected_techs = [
                f"`{t.name} ({int(t.confidence_score * 100)}%)`"
                for t in report.tech_stack.technology_signals
                if t.detection_status == "suspected"
            ]
            st.markdown(
                f"**✅ Confirmed Technologies (Headers / Scripts / DOM):** "
                f"{' '.join(confirmed_techs) or '`None confirmed`'}"
            )
            st.markdown(
                f"**🔍 Suspected / Inferred Technologies (Job Postings & Text Mentions):** "
                f"{' '.join(suspected_techs) or '`None suspected`'}"
            )

            tech_rows = [
                {
                    "Technology": t.name,
                    "Status": "✅ Confirmed" if t.detection_status == "confirmed" else "🔍 Suspected",
                    "Confidence": f"{t.confidence_score:.2f} ({int(t.confidence_score * 100)}%)",
                    "Signal Source": t.signal_source,
                    "Detected At (UTC)": t.detected_at,
                }
                for t in report.tech_stack.technology_signals
            ]
            st.dataframe(tech_rows, width="stretch", hide_index=True)
        else:
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
        st.markdown("### 🔬 5-Step Fact-Check & Semantic Claim Grounding Audit")
        if report.verified_claims:
            status_badges = {
                "verified": "✅ Verified in Re-Fetched Source",
                "partially_supported": "⚠️ Partially Supported ([Partially Supported])",
                "inferred_hypothesis": "🔍 Unverified ([Hypothesis / Inferred])",
            }
            category_labels = {
                "executive_summary": "Executive Summary",
                "news_trigger": "News Trigger",
                "pain_point": "Pain Point",
                "tech_stack": "Tech-Stack & Infrastructure",
            }
            for vc in report.verified_claims:
                badge = status_badges.get(vc.verification_status, vc.verification_status)
                cat_label = category_labels.get(vc.category, vc.category)
                refetch_badge = "🌐 Re-Fetch: OK" if vc.source_refetched else "⚠️ Re-Fetch: Failed (Unverified)"
                st.markdown(
                    f"- **{badge}** (`Grounding: {vc.grounding_score:.2f}` · "
                    f"`Semantic: {vc.semantic_score:.2f}` · `{refetch_badge}` · *{cat_label}*): **{vc.claim}**  \n"
                    f"  ↳ *Source:* [{vc.source_title or vc.source_url}]({vc.source_url})  \n"
                    f"  ↳ *Extracted Original Passage:* `\"{vc.matched_excerpt}\"`"
                )
        else:
            st.caption("Fact-checking audit disabled or no claims recorded.")

        st.divider()
        st.markdown("### 🔗 Verified & Scored Source Citations (Multi-Source Evaluation)")
        for idx, src in enumerate(report.sources, start=1):
            date_parts: list[str] = []
            if src.published_date:
                date_parts.append(f"📅 Published: `{src.published_date}`")
            if src.updated_date:
                date_parts.append(f"🔄 Updated: `{src.updated_date}`")
            if src.age_days is not None:
                date_parts.append(f"⏱️ Age: `{src.age_days}d` (Recency: `{src.recency_score:.2f}`)")
            date_tag = f" · {' · '.join(date_parts)}" if date_parts else ""
            st.markdown(
                f"{idx}. **[{src.title}]({src.url})**  \n"
                f"   🏷️ `{src.source_type}`{date_tag}  \n"
                f"   🏛️ **Source Quality (Quellenqualität):** `{src.source_quality_score:.2f}` "
                f"*(Authority: `{src.credibility_score:.2f}` · Recency: `{src.recency_score:.2f}`)* · "
                f"📝 **Statement Quality (Aussagequalität):** `{src.statement_quality_score:.2f}` · "
                f"⭐ **Composite:** `{src.composite_score:.2f}`  \n"
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
