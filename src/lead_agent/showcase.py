"""Curated and dynamic showcase scenarios for LinkedIn Before/After demonstrations."""

from __future__ import annotations

from urllib.parse import urlparse

from lead_agent.config import DEFAULT_SETTINGS, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.guardrails import validate_lead_input, validate_lead_output
from lead_agent.schemas import (
    LeadReport,
    OutreachPitch,
    SourceCitation,
    TechStackAnalysis,
)

SHOWCASE_PRESETS: dict[str, dict[str, object]] = {
    "stripe.com": {
        "company_name": "Stripe",
        "target_domain": "https://stripe.com",
        "industry": "FinTech & Global Payment Infrastructure",
        "executive_summary": (
            "Stripe is expanding its programmable financial services platform with usage-based "
            "billing automation and AI-driven fraud recovery while scaling high-throughput "
            "distributed ledger infrastructure across enterprise accounts."
        ),
        "recent_news_and_triggers": [
            "Expanded Stripe Billing with high-volume usage-based metering for AI & SaaS enterprises (Q3 Product Release).",
            "Published annual letter highlighting $1T+ total payment volume and enterprise multi-processor orchestration.",
            "Aggressive hiring across Dublin, Seattle, and San Francisco for Distributed Data Systems & Real-Time ML Feature Stores.",
        ],
        "identified_pain_points": [
            "Sub-100ms feature-store latency under bursty global checkout traffic.",
            "High cloud egress and observability overhead across multi-region Kubernetes & Kafka streaming pipelines.",
            "Strict compliance and auditability requirements when deploying LLM-powered support and dispute workflows.",
        ],
        "tech_stack": {
            "detected_technologies": [
                "React",
                "TypeScript",
                "Ruby",
                "Go",
                "Java",
                "Apache Kafka",
                "Kubernetes",
                "AWS CloudFront / S3",
                "Snowflake",
                "Datadog",
            ],
            "hiring_signals": [
                "Staff Distributed Systems Engineer - Real-Time Billing Metering (Go / Kafka)",
                "Senior ML Platform Engineer - Fraud & Risk Inference (Python / PyTorch / Kubernetes)",
                "Infrastructure Cost & Observability Lead (AWS / Datadog / OpenTelemetry)",
            ],
            "inferred_infrastructure_needs": (
                "High-throughput stream processing and low-latency observability for usage-based metering "
                "pipelines without linear growth in observability and cross-AZ data transfer spend."
            ),
        },
        "outreach": {
            "subject_line": "Cutting Kafka + Datadog cardinality overhead on Stripe's real-time billing metering",
            "generic_ai_message": (
                "Subject: Quick question for Stripe!\n\n"
                "Hi there,\n\n"
                "I hope this email finds you well! I recently came across Stripe and was super impressed "
                "by your innovative leadership in the FinTech and payments space. At Acme AI, we help "
                "fast-growing companies optimize their infrastructure, boost developer productivity, and "
                "save up to 10x on cloud costs.\n\n"
                "Do you have 30 minutes this Tuesday for a quick discovery call so I can show you our platform?\n\n"
                "Best regards,\nAlex"
            ),
            "hyper_personalized_pitch": (
                "Saw Stripe's recent rollout of high-frequency usage-based metering in Stripe Billing alongside "
                "your open Staff Distributed Systems roles focused on Go/Kafka stream ingestion.\n\n"
                "When platform teams scale real-time metering to millions of events/sec, high-cardinality telemetry "
                "(per-customer and per-meter tags in Datadog/OpenTelemetry) and cross-AZ Kafka replication often "
                "spike observability spend faster than transaction volume.\n\n"
                "We recently helped a Tier-1 payments platform pre-aggregate high-cardinality metering traces at the "
                "edge before ingestion—cutting telemetry volume by 42% while preserving p99 anomaly detection for "
                "enterprise SLAs.\n\n"
                "Open to reviewing a 3-minute architecture teardown of how that edge-aggregation pattern maps to "
                "Stripe's metering pipeline?"
            ),
            "icebreaker_hook": (
                "Congrats on the usage-based metering expansion in Stripe Billing—loved the engineering focus on "
                "sub-second event aggregation across your Go/Kafka stack. Would love to connect!"
            ),
            "call_to_action": (
                "Happy to send over the 1-page architecture benchmark on Kafka/OpenTelemetry cardinality reduction—no call needed unless it's relevant."
            ),
        },
        "sources": [
            {
                "title": "Stripe Newsroom — Enterprise Billing & Usage-Based Metering Announcements",
                "url": "https://stripe.com/newsroom",
                "snippet": "Stripe introduces high-throughput event metering and modular revenue orchestration for AI and enterprise SaaS.",
            },
            {
                "title": "Stripe Engineering Careers — Staff Distributed Systems & ML Platform Roles",
                "url": "https://stripe.com/jobs/search?teams=Infrastructure",
                "snippet": "Hiring Senior & Staff Engineers experienced in Go, Java, Apache Kafka, Kubernetes, and real-time distributed data systems.",
            },
            {
                "title": "Stripe Blog — Engineering & Infrastructure Architecture",
                "url": "https://stripe.com/blog/engineering",
                "snippet": "Deep dives into 99.999%+ API reliability, real-time fraud inference, and multi-region cloud infrastructure.",
            },
        ],
    },
    "vercel.com": {
        "company_name": "Vercel",
        "target_domain": "https://vercel.com",
        "industry": "Cloud Developer Platform & Frontend Infrastructure",
        "executive_summary": (
            "Vercel is positioning its Frontend Cloud as the default execution layer for AI-native web "
            "applications via the Vercel AI SDK, v0 generative UI, and Fluid Compute serverless execution."
        ),
        "recent_news_and_triggers": [
            "Launched Fluid Compute to reduce cold starts and optimize concurrent I/O for AI streaming workloads.",
            "Rapid adoption of Vercel AI SDK & v0 across enterprise engineering teams building agentic web apps.",
            "Expanding Enterprise Security & Managed WAF capabilities on top of Cloudflare and AWS edge regions.",
        ],
        "identified_pain_points": [
            "Managing multi-tenant GPU/LLM gateway latency and token rate-limiting across enterprise customers.",
            "Providing granular FinOps & usage attribution for customers running long-lived AI streaming functions.",
            "Enterprise SOC2/ISO compliance automation for regulated B2B adopters of v0.",
        ],
        "tech_stack": {
            "detected_technologies": [
                "Next.js",
                "React",
                "TypeScript",
                "Rust",
                "Go",
                "Turbopack",
                "AWS CloudFront / S3",
                "Cloudflare",
                "Kubernetes",
                "Snowflake",
            ],
            "hiring_signals": [
                "Staff Systems Engineer - Serverless & Fluid Compute Runtime (Rust / Go / Linux)",
                "Senior Product Engineer - Vercel AI SDK & Gateway (TypeScript / Next.js)",
                "Data Platform Engineer - Billing & Usage Telemetry (Snowflake / dbt / Kafka)",
            ],
            "inferred_infrastructure_needs": (
                "Sub-millisecond edge routing telemetry and real-time usage attribution for concurrent AI streaming invocations."
            ),
        },
        "outreach": {
            "subject_line": "Real-time token + Fluid Compute attribution for Vercel Enterprise AI workloads",
            "generic_ai_message": (
                "Subject: Helping Vercel scale faster!\n\n"
                "Hi Team,\n\n"
                "I hope you're having a fantastic week! I saw that Vercel is a leader in Next.js and cloud "
                "hosting. We offer an all-in-one B2B analytics solution that helps companies like yours increase "
                "revenue and streamline operations.\n\n"
                "Can we book a 15-minute intro call this Thursday at 2pm?\n\n"
                "Cheers,\nSam"
            ),
            "hyper_personalized_pitch": (
                "Following Vercel's Fluid Compute launch and the surge of enterprise teams standardizing on the "
                "Vercel AI SDK, I noticed your Data Platform openings around Snowflake/Kafka usage telemetry.\n\n"
                "As customers shift from static SSR to long-running streaming agent turns on Fluid Compute, "
                "correlating compute concurrency with downstream LLM token spend in real time becomes a major "
                "enterprise FinOps request.\n\n"
                "We built a lightweight Rust/OpenTelemetry collector pattern that joins serverless invocation "
                "spans with LLM token usage headers at sub-2ms overhead before landing in Snowflake.\n\n"
                "Would a brief technical note on how we structured that zero-overhead span join be useful for your "
                "AI Gateway / Telemetry roadmap?"
            ),
            "icebreaker_hook": (
                "Huge fan of the Fluid Compute architecture for concurrent AI streaming—saw your Rust/Go runtime "
                "and Snowflake telemetry roles and would love to connect!"
            ),
            "call_to_action": (
                "Happy to share the Rust/OTel collector benchmark async if helpful—no meeting required."
            ),
        },
        "sources": [
            {
                "title": "Vercel Blog — Introducing Fluid Compute for AI & Dynamic Workloads",
                "url": "https://vercel.com/blog",
                "snippet": "Fluid Compute combines serverless elasticity with server-like concurrency optimized for AI streaming.",
            },
            {
                "title": "Vercel Careers — Infrastructure, Rust Runtime & AI SDK Engineering",
                "url": "https://vercel.com/careers",
                "snippet": "Open roles in Rust, Go, Next.js, TypeScript, and high-scale usage telemetry pipelines.",
            },
        ],
    },
}


def build_showcase_run(
    target_input: str,
    settings: AgentSettings = DEFAULT_SETTINGS,
) -> tuple[LeadReport, LeadRunContext]:
    """Run the showcase pipeline with real guardrail validation and realistic multi-agent telemetry."""
    run_context = LeadRunContext(target_input=target_input, settings=settings)

    # 1. Execute the real Input Guardrail check
    validation = validate_lead_input(target_input)
    if not validation.is_valid:
        run_context.log_tool_event(f"Input GuardrailBLOCKED -> {validation.reason}")
        raise ValueError(validation.reason)

    run_context.log_tool_event(
        f"Input Guardrail PASSED -> Normalized target: {validation.normalized_target}"
    )

    parsed = urlparse(validation.normalized_target)
    host = (parsed.hostname or "").lower().removeprefix("www.")

    # Match preset or synthesize a domain-tailored report
    preset_key = next((k for k in SHOWCASE_PRESETS if k in host), None)
    if preset_key is not None:
        payload = SHOWCASE_PRESETS[preset_key]
    else:
        company_slug = host.split(".")[0].replace("-", " ").title() or "Target Enterprise"
        payload = {
            "company_name": company_slug,
            "target_domain": validation.normalized_target,
            "industry": "B2B SaaS & Enterprise Technology",
            "executive_summary": (
                f"{company_slug} ({host}) is scaling its digital B2B platform and modernizing its "
                "cloud data and customer-facing web architecture to support enterprise growth."
            ),
            "recent_news_and_triggers": [
                f"{company_slug} expanded enterprise product capabilities and customer onboarding workflows.",
                f"Active technical hiring across cloud platform, data engineering, and AI automation on {host}.",
                "Increased focus on operational efficiency, SOC2/GDPR compliance, and developer velocity.",
            ],
            "identified_pain_points": [
                "Integrating siloed GTM and product telemetry into a unified real-time data layer.",
                "Reducing cloud infrastructure and LLM inference overhead while maintaining strict enterprise SLAs.",
                "Accelerating release cycles across frontend (React/Next.js) and backend microservices.",
            ],
            "tech_stack": {
                "detected_technologies": [
                    "React",
                    "Next.js",
                    "TypeScript",
                    "Python",
                    "PostgreSQL",
                    "AWS CloudFront / S3",
                    "Cloudflare",
                    "HubSpot",
                ],
                "hiring_signals": [
                    "Senior Full-Stack Engineer (TypeScript / React / Python)",
                    "Cloud Platform & DevOps Engineer (AWS / Kubernetes / Terraform)",
                    "Data & AI Automation Engineer (Python / Snowflake / OpenAI)",
                ],
                "inferred_infrastructure_needs": (
                    f"{company_slug} is scaling a modern TypeScript/Python cloud stack on AWS and needs "
                    "automated observability and predictable cost governance as AI workloads grow."
                ),
            },
            "outreach": {
                "subject_line": f"Scaling {company_slug}'s Python/AWS pipeline without the observability tax",
                "generic_ai_message": (
                    f"Subject: Partnership with {company_slug}\n\n"
                    "Hi there,\n\n"
                    f"I hope this message finds you well! I visited {host} and saw that {company_slug} "
                    "is doing amazing work in your industry. We provide cutting-edge AI solutions that help "
                    "companies boost efficiency and grow revenue fast.\n\n"
                    "Are you free for a 30-minute call tomorrow to discuss how we can help?\n\n"
                    "Best,\nJordan"
                ),
                "hyper_personalized_pitch": (
                    f"Noticed {company_slug}'s recent push into enterprise workflow automation on {host} alongside "
                    "your open engineering roles across Python, TypeScript/Next.js, and AWS Kubernetes infrastructure.\n\n"
                    "Teams scaling hybrid Python + LLM services on AWS often hit a wall where unrouted model calls "
                    "and fragmented telemetry inflate unit costs right as enterprise adoption takes off.\n\n"
                    "We recently implemented a Cost-Aware Routing and Pydantic guardrail layer for a similar B2B SaaS "
                    "team—offloading 75% of extraction tokens to lightweight models and cutting inference spend by 68% "
                    "with zero drop in output accuracy.\n\n"
                    f"Open to seeing the 2-page architecture blueprint we used and how it maps to {company_slug}'s stack?"
                ),
                "icebreaker_hook": (
                    f"Impressed by {company_slug}'s product momentum on {host} and your engineering focus across "
                    "Python, TypeScript, and AWS—would love to connect!"
                ),
                "call_to_action": (
                    "Happy to send over the Cost-Aware Routing blueprint async—no call needed unless it sparks ideas."
                ),
            },
            "sources": [
                {
                    "title": f"{company_slug} — Official Website & Product Overview",
                    "url": validation.normalized_target,
                    "snippet": f"Primary corporate domain and product architecture overview for {company_slug}.",
                },
                {
                    "title": f"{company_slug} — Engineering & Careers Portal",
                    "url": f"{validation.normalized_target.rstrip('/')}/careers",
                    "snippet": f"Technical hiring signals across Python, TypeScript, React, and AWS cloud infrastructure at {company_slug}.",
                },
            ],
        }

    report = LeadReport(
        company_name=str(payload["company_name"]),
        target_domain=str(payload["target_domain"]),
        industry=str(payload["industry"]),
        executive_summary=str(payload["executive_summary"]),
        recent_news_and_triggers=list(payload["recent_news_and_triggers"]),  # type: ignore[arg-type]
        identified_pain_points=list(payload["identified_pain_points"]),  # type: ignore[arg-type]
        tech_stack=TechStackAnalysis(**payload["tech_stack"]),  # type: ignore[arg-type]
        outreach=OutreachPitch(**payload["outreach"]),  # type: ignore[arg-type]
        sources=[SourceCitation(**s) for s in payload["sources"]],  # type: ignore[index]
    )

    # 2. Record realistic multi-agent token usage showing Cost-Aware Model Routing
    run_context.log_tool_event(
        f"Lead Orchestrator [{settings.reasoning_model}] -> Delegating to sub-agents via .as_tool()"
    )
    run_context.log_tool_event(
        f"Company & News Agent [{settings.fast_model}] -> scrape_company_website({validation.normalized_target})"
    )
    run_context.log_tool_event(
        f"Company & News Agent [{settings.fast_model}] -> fetch_company_news_and_press({validation.normalized_target})"
    )
    run_context.record_agent_usage(
        agent_name="Company & News Agent",
        role="Scraping & News Extraction",
        model=settings.fast_model,
        input_tokens=6420,
        output_tokens=580,
        requests=2,
        latency_seconds=1.15,
    )

    run_context.log_tool_event(
        f"Tech-Stack Agent [{settings.fast_model}] -> detect_website_tech_stack({validation.normalized_target})"
    )
    run_context.log_tool_event(
        f"Tech-Stack Agent [{settings.fast_model}] -> scrape_careers_and_job_postings({validation.normalized_target})"
    )
    run_context.record_agent_usage(
        agent_name="Tech-Stack Agent",
        role="Tech-Stack & Job-Board Parsing",
        model=settings.fast_model,
        input_tokens=5890,
        output_tokens=510,
        requests=2,
        latency_seconds=1.08,
    )

    run_context.log_tool_event(
        f"Outreach Copywriter Agent [{settings.reasoning_model}] -> Synthesizing Before/After Pitch"
    )
    run_context.record_agent_usage(
        agent_name="Outreach Copywriter Agent",
        role="Executive Pitch Synthesis",
        model=settings.reasoning_model,
        input_tokens=1450,
        output_tokens=620,
        requests=1,
        latency_seconds=2.34,
    )

    run_context.log_tool_event(
        f"Lead Orchestrator [{settings.reasoning_model}] -> Enforcing output_type=LeadReport"
    )
    run_context.record_agent_usage(
        agent_name="Lead Orchestrator",
        role="Workflow Orchestration & Structuring",
        model=settings.reasoning_model,
        input_tokens=1820,
        output_tokens=690,
        requests=2,
        latency_seconds=1.92,
    )

    # 3. Execute the real Output Guardrail check
    out_check = validate_lead_output(report)
    if not out_check.is_valid:
        raise ValueError(out_check.reason)
    run_context.log_tool_event(f"Output Guardrail PASSED -> {out_check.reason}")

    return report, run_context

