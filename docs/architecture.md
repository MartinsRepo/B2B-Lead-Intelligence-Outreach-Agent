# System Architecture — B2B Lead Intelligence & Outreach Agent

## 1. End-to-End Architecture Overview

The **B2B Lead Intelligence & Outreach Agent** uses the **OpenAI Agents SDK** (`Agents-as-Tools` pattern via `.as_tool()`) to separate high-volume web scraping and HTML parsing from high-reasoning synthesis and executive copywriting.

```mermaid
flowchart TD
    INPUT["[User Input: Target Company Domain / Corporate URL]"] --> IG["[Configurable Input Guardrail]<br/>- Corporate Domain & URL Regex Validation<br/>- Optional Private / Localhost IP SSRF Tripwire<br/>(Prevents token spend on malformed inputs)"]
    IG --> ORCH["[Lead Orchestrator]<br/>Controls end-to-end workflow (gpt-6.2-sol)"]

    ORCH -->|".as_tool() (toggleable)"| CNA["[Company & News Agent]<br/>(gpt-6-luna)"]
    ORCH -->|".as_tool() (toggleable)"| TSA["[Tech-Stack Agent]<br/>(gpt-6-luna)"]
    ORCH -->|".as_tool() (toggleable)"| OCA["[Outreach Copywriter Agent]<br/>(gpt-6.2-sol)"]

    CNA --> WNS["[Web / News Scraper]<br/>(HTTPX + BeautifulSoup4)"]
    TSA --> JBP["[Job-Board & HTML Parser]<br/>(HTTPX + BS4 + Tech Fingerprinting)"]

    WNS --> OG["[Configurable Output Guardrail & Structured Output]<br/>- Enforces min. verified HTTP/HTTPS source citations<br/>- Validates min. pitch length & customizable anti-spam filter<br/>- Enforces Pydantic v2 schema (output_type=LeadReport)"]
    JBP --> OG
    OCA --> OG

    OG --> UI["[Streamlit Production UI + Real-Time Cost & Token Telemetry]"]
```

---

## 2. Multi-Agent Roles & Cost-Aware Model Routing

A common anti-pattern in agentic workflows is sending raw HTML, press releases, and job descriptions directly into a frontier reasoning model. In this architecture, tasks are split across two pricing tiers configured in [`src/lead_agent/config.py`](../src/lead_agent/config.py):

| Agent | Role | Default Model (`LIVE_MODEL_ALIASES`) | Tier | Tools / Output |
| :--- | :--- | :--- | :--- | :--- |
| **Company & News Agent** | Scrapes homepage, `/news`, `/press`, and `/blog` to extract strategic triggers | `gpt-6-luna` (`gpt-4o-mini`) | ⚡ Fast (`$0.15 / 1M in`) | `scrape_company_website`, `fetch_company_news_and_press` |
| **Tech-Stack Agent** | Fingerprints HTTP headers, DOM scripts, and `/careers` job boards for tech signals | `gpt-6-luna` (`gpt-4o-mini`) | ⚡ Fast (`$0.15 / 1M in`) | `detect_website_tech_stack`, `scrape_careers_and_job_postings` |
| **Outreach Copywriter Agent** | Synthesizes research into a single-prompt baseline vs. multi-agent grounded pitch | `gpt-6.2-sol` (`gpt-4o`) | 🧠 Reasoning (`$2.50 / 1M in`) | `output_type=OutreachPitch` |
| **Lead Orchestrator** | Coordinates `.as_tool()` sub-agents, enforces guardrails, and emits `LeadReport` | `gpt-6.2-sol` (`gpt-4o`) | 🧠 Reasoning (`$2.50 / 1M in`) | `output_type=LeadReport` |

### Why Cost-Aware Routing Matters
A large share of total input tokens occurs during raw webpage and job-board ingestion. By routing the `Company & News Agent` and `Tech-Stack Agent` to the fast tier (`gpt-6-luna` / `gpt-4o-mini`) while reserving the reasoning tier (`gpt-6.2-sol` / `gpt-4o`) for orchestration and final pitch synthesis, total run cost is reduced significantly compared to an all-reasoning baseline without sacrificing copywriting quality.

### Live Model Alias Resolution (`resolve_live_model_name`)
In [`src/lead_agent/agents/orchestrator.py`](../src/lead_agent/agents/orchestrator.py), `LIVE_MODEL_ALIASES` transparently maps the architectural specification model names (`gpt-6-luna` → `gpt-4o-mini`, `gpt-6.2-sol` → `gpt-4o`) when calling the live OpenAI API while preserving the configured model identifiers and pricing tiers in telemetry reports.

---

## 3. Configurable Guardrails & Sub-Agent Policy (`src/lead_agent/guardrails.py` & `config.py`)

All guardrails and `.as_tool()` sub-agent delegations are dynamically configurable at runtime via `AgentSettings` and the Streamlit sidebar Control Plane:

### 1. Input Guardrail (`@input_guardrail`)
- **`enable_input_guardrail` (`bool`, default `True`):** Executed **before** the orchestrator invokes any LLM or sub-agent. Validates that the user provided a well-formed corporate domain (e.g., `bmwgroup.com/en`, `stripe.com`, `https://vercel.com`).
- **`block_private_ips` (`bool`, default `True`):** SSRF tripwire that blocks loopback and private network targets (`localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, `.local`, `.internal`) by triggering `tripwire_triggered=True`.

### 2. Modular Agents-as-Tools (`.as_tool()`) Delegation
- **`enable_company_news_agent` (`bool`, default `True`):** Attaches/detaches `company_news_research_tool`.
- **`enable_tech_stack_agent` (`bool`, default `True`):** Attaches/detaches `tech_stack_detection_tool`.
- **`enable_copywriter_agent` (`bool`, default `True`):** Attaches/detaches `outreach_copywriter_tool`.

### 3. Output Guardrail (`@output_guardrail`)
- **`enable_output_guardrail` (`bool`, default `True`):** Validates the structured `LeadReport` before returning it to the UI or downstream CRM.
- **`min_sources_required` (`int`, default `1`):** Enforces a minimum count of verified `http://` or `https://` citations in `report.sources`.
- **`min_pitch_length` (`int`, default `40`):** Ensures `hyper_personalized_pitch` meets minimum character length thresholds.
- **`enable_anti_spam_check` (`bool`, default `True`) & `blocked_spam_phrases` (`tuple[str, ...]`):** Scans generated outreach copy against a customizable list of prohibited spam clichés.

---

## 4. Deterministic Structured Outputs (`src/lead_agent/schemas.py`)

By passing `output_type=LeadReport` to the `Lead Orchestrator`, the OpenAI Agents SDK enforces strict adherence to the Pydantic v2 schema:
- `LeadReport`: Top-level container with `company_name`, `target_domain`, `industry`, `executive_summary`, `recent_news_and_triggers`, and `identified_pain_points`.
- `TechStackAnalysis`: Lists `detected_technologies`, `hiring_signals`, and `inferred_infrastructure_needs`.
- `OutreachPitch`: Contains both `generic_ai_message` (Standard Single-Prompt Baseline) and `hyper_personalized_pitch` (Multi-Agent Grounded Pitch), plus `subject_line`, `icebreaker_hook`, and `call_to_action`.
- `SourceCitation`: Enforces valid HTTP/HTTPS URLs (`url`), `title`, and factual `snippet`.

---

## 5. Real-Time Observability & Streamlit Async Architecture (`src/lead_agent/context.py` & `ui/app.py`)

### Token & Cost Telemetry
`LeadRunContext` is passed across the execution tree via `RunContextWrapper[LeadRunContext]`. Combined with `TelemetryAgentHooks` (`on_start` / `on_end`) and SDK `RequestUsage`:
- Tracks `input_tokens`, `output_tokens`, `total_tokens`, `requests`, and wall-clock `latency_seconds` per agent.
- Computes both the **actual routed cost** and the **hypothetical all-reasoning baseline cost**, surfacing exact dollar and percentage savings live in the 4-column Telemetry Card.

### Persistent Background Event-Loop Thread (`_get_background_event_loop`)
Streamlit runs inside an asynchronous Uvicorn server and re-executes the UI script on every widget interaction. To prevent `RuntimeError: Event loop is closed` or collisions with Uvicorn's thread loop across reruns:
- [`ui/app.py`](../ui/app.py) initializes a dedicated background daemon thread via `@st.cache_resource` running a persistent `asyncio` event loop (`loop.run_forever()`).
- Agent pipeline executions are submitted thread-safely via `asyncio.run_coroutine_threadsafe(coro, loop).result()`, keeping the SDK's internal `AsyncOpenAI` / `httpx.AsyncClient` connection pool bound to a single open event loop throughout the application lifecycle.
