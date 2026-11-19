
![intro](gallery/b2b_latest.png)

# B2B Lead Intelligence & Outreach Agent
## ✨Ideation and Implementation
- Ideation: ChatGPT and Gemini 3 Pro
- Implementation: Antigravity Agent

An autonomous multi-agent B2B sales research and hyper-personalized outreach pipeline built with the **OpenAI Agents SDK**, **Pydantic v2**, **HTTPX / BeautifulSoup4**, and **Streamlit**.

Given a target company domain (e.g., `bmwgroup.com/en`, `stripe.com`, `vercel.com`) or corporate URL, the agent team validates the target through configurable **Input Guardrails**, scrapes press releases and company news across multiple channels, fingerprints the web & cloud tech stack with evidence-based confidence scores, analyzes open engineering job postings for hiring signals, verifies claims against re-fetched source passages, and synthesizes an executive **Outreach & Phone Call Brief** (grounded email pitch, short-form DM icebreaker, low-friction CTA, and a 5-point live phone call cheat-sheet) with real-time token and cost telemetry.

---

## ✨ Key Features

- **Multi-Agent Orchestration (`.as_tool()` Pattern):** Uses the OpenAI Agents SDK to coordinate three specialized sub-agents (`Company & News Agent`, `Tech-Stack Agent`, and `Outreach Copywriter Agent`) under a central `Lead Orchestrator`.
- **Cost-Aware Model Routing:** Routes high-volume HTML scraping and job-board extraction tasks to a fast, low-cost model tier (`gpt-6-luna` / `gpt-4o-mini`) while reserving a high-reasoning model tier (`gpt-6.2-sol` / `gpt-4o`) for orchestration and executive copywriting.
- **Multi-Source Research & Dual Source/Statement Scoring:** Combines corporate newsroom subpage crawling, RSS/Atom feed auto-discovery, JSON-LD & Next.js (`__NEXT_DATA__`) hydration extraction (with automatic JS reader fallback for SPAs), and external Google News RSS search. Distinguishes **`published_date`** vs. **`updated_date`**, calculates actual article age in days (**`age_days`**) with time-decay recency, and separately scores **`source_quality_score` (*Quellenqualität*)** and **`statement_quality_score` (*Aussagequalität*)**.
- **5-Step Semantic Fact-Verification & Claim-Grounding Engine:** Audits all core statements (`executive_summary`, `recent_news_and_triggers`, `identified_pain_points`, and `tech_stack`) by (1) linking each claim to a source reference, (2) requiring a **successful live HTTP re-fetch (`source_refetched=True`)** for full verification, (3) extracting the matching passage, (4) scoring both lexical coverage and **semantic similarity** (B2B concept clusters, character 3-gram cosine similarity, and negation/contradiction detection), and (5) separately labeling partially supported statements (`[Partially Supported]`) versus unverifiable hypotheses (`[Hypothesis / Inferred]` or discarding them).
- **Evidence-Based Tech-Stack Detection:** Eliminates keyword false positives by recording a `DetectedTechnology` profile for every signal—including **`confidence_score` (`0.00–1.00`)**, **`signal_source`** (`http_header`, `script_asset`, `meta_generator`, `job_posting_requirement`, `body_text_mention`), **`detected_at` UTC timestamp**, and an explicit distinction between **`confirmed`** (*sicher erkannt*, `>= 0.80`) and **`suspected`** (*vermutet*, `< 0.80`).
- **Configurable Guardrails & Multi-Layer SSRF / DNS-Rebinding Defense (`security.py`):**
  - *Fail-Closed Input Guardrail & IP-Pinned SSRF Protection:* Validates domain/corporate URL format, blocks all private/loopback/link-local/CGNAT/cloud-metadata IPv4 & IPv6 ranges (`169.254.169.254`, `10.0.0.0/8`, `127.0.0.0/8`, `100.64.0.0/10`, `fc00::/7`), enforces **Fail-Closed DNS resolution (`strict_dns_failure=True`)**, **pins the validated IP address at connection time** (while preserving the original `Host` header and TLS `sni_hostname` certificate verification to prevent TOCTOU DNS rebinding), **re-validates every HTTP redirect hop (`301/302/303/307/308`)**, and sanitizes all discovered RSS feed and external source URLs.
  - *Modular `.as_tool()` Toggles:* Enable or disable individual sub-agents on the fly from the Streamlit sidebar.
  - *Output Guardrail:* Enforces configurable minimum verified HTTP/HTTPS source citations, minimum source quality scores, minimum pitch length, and customizable anti-spam phrase filtering.
- **Deterministic Structured Outputs:** Enforces strict JSON schemas using Pydantic v2 (`output_type=LeadReport`), eliminating unstructured Markdown chaos for reliable UI rendering and downstream CRM export.
- **Real-Time Observability:** Tracks per-agent latency, `input_tokens`, `output_tokens`, API request counts, and USD cost savings via `RunContextWrapper` and `RequestUsage` in a live 4-column telemetry card.

---

## 🏗️ System Architecture


For a deep dive into the internals, model alias resolution, guardrail policy rules, and persistent async event-loop management, see [`docs/architecture.md`](docs/architecture.md).

---

## 📂 Project Structure

```text
B2B-Lead-Intelligence-Outreach-Agent/
├── .github/workflows/ci.yml        # GitHub Actions CI (Ruff + Pytest)
├── docs/
│   └── architecture.md             # Detailed technical architecture documentation
├── gallery/
│   └── b2b_latest.png              # Pictures
├── src/lead_agent/
│   ├── __init__.py
│   ├── config.py                   # Cost-Aware Routing, pricing & guardrail policy settings
│   ├── context.py                  # RunContextWrapper token & cost observability
│   ├── fact_checker.py             # 5-step source re-fetch, passage extraction & claim verification
│   ├── guardrails.py               # Configurable @input_guardrail & @output_guardrail
│   ├── schemas.py                  # Pydantic v2 models (LeadReport, VerifiedClaim, etc.)
│   ├── security.py                 # Multi-layer SSRF protection, DNS checks & redirect-safe HTTP client
│   ├── agents/
│   │   ├── company_news_agent.py   # Fast-tier web & press release researcher
│   │   ├── tech_stack_agent.py     # Fast-tier HTML & job-board tech stack parser
│   │   ├── copywriter_agent.py     # Reasoning-tier B2B outreach copywriter
│   │   └── orchestrator.py         # Lead Orchestrator wiring sub-agents via .as_tool()
│   └── tools/
│       ├── research_engine.py      # Multi-source news aggregator, JSON-LD/SPA extractor & source scoring
│       ├── web_scraper.py          # Website & multi-channel press scraper
│       └── tech_parser.py          # Tech fingerprinting & careers page parser
├── tests/                          # Comprehensive unit & integration test suite (63 tests)
├── ui/
│   └── app.py                      # Streamlit production UI & guardrail control plane
├── .env.example                    # Environment variable template
├── pyproject.toml                  # Dependencies and tool configuration
└── README.md
```

---

## 🚀 Quickstart

### 1. Install Dependencies

```powershell
pip install -e ".[dev]"
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and set your OpenAI API key:

```powershell
# Windows (CMD / PowerShell)
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

```dotenv
OPENAI_API_KEY="sk-YOUR_OPENAI_API_KEY"
FAST_MODEL="gpt-6-luna"
REASONING_MODEL="gpt-6.2-sol"
```

### 3. Launch the Streamlit Application

```powershell
python -m streamlit run ui/app.py
```

---

## 🧪 Running Tests & Linting

Run the automated test suite and code quality checks:

```powershell
python -m pytest -v
python -m ruff check src tests ui
```
