"""Evidence-based tech-stack and job-board HTML parsing tools for the Tech-Stack Agent."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

try:
    from agents import RunContextWrapper, function_tool
except ImportError:  # pragma: no cover
    RunContextWrapper = object  # type: ignore[misc,assignment]

    def function_tool(func=None, **_kwargs):  # type: ignore[no-redef]
        if func is None:
            return lambda f: f
        return func


from lead_agent.config import DEFAULT_SETTINGS
from lead_agent.context import LeadRunContext
from lead_agent.privacy import scrub_personal_data, strip_personal_dom_elements
from lead_agent.security import SSRFBlockedError, safe_http_get
from lead_agent.tools.web_scraper import DEFAULT_HEADERS, normalize_target_url

CONFIRMED_THRESHOLD = 0.80

# 1. High-Confidence HTTP Header Rules (Confirmed: 0.94 - 0.98)
HEADER_TECH_RULES: tuple[tuple[str, str, str, float], ...] = (
    # (Technology Name, Header Key Substring, Header Value Pattern, Confidence)
    ("Cloudflare", "server", r"cloudflare", 0.98),
    ("Cloudflare", "cf-ray", r".+", 0.98),
    ("Vercel", "x-vercel-id", r".+", 0.98),
    ("Vercel", "server", r"vercel", 0.97),
    ("AWS CloudFront / S3", "x-amz-cf-id", r".+", 0.97),
    ("AWS CloudFront / S3", "x-amz-request-id", r".+", 0.96),
    ("AWS CloudFront / S3", "via", r"cloudfront\.net", 0.96),
    ("AWS CloudFront / S3", "server", r"amazons3|awselb", 0.96),
    ("Next.js", "x-powered-by", r"next\.js", 0.97),
    ("Express / Node.js", "x-powered-by", r"express", 0.94),
)

# 2. High-Confidence Script / Link / DOM Asset Rules (Confirmed: 0.90 - 0.96)
ASSET_AND_DOM_RULES: tuple[tuple[str, str, tuple[str, ...], float], ...] = (
    # (Technology Name, Signal Category, Patterns in <script src>/<link href>/DOM attrs, Confidence)
    ("Next.js", "script_or_dom_asset", ("/_next/static/", "__next_data__", "next-route-announcer"), 0.96),
    ("React", "script_or_dom_asset", ("react-dom", "data-reactroot", "__react"), 0.92),
    ("Vue.js", "script_or_dom_asset", ("vue.runtime", "vue.global", "data-v-"), 0.92),
    ("Angular", "script_or_dom_asset", ("ng-version", "angular.min.js"), 0.93),
    ("Tailwind CSS", "stylesheet_or_dom_class", ("tailwindcss", "--tw-"), 0.88),
    ("Stripe", "script_asset", ("js.stripe.com", "stripe-js"), 0.96),
    ("Segment", "script_asset", ("cdn.segment.com", "analytics.load"), 0.94),
    ("HubSpot", "script_asset", ("js.hs-scripts.com", "hs-analytics", "js.hsforms.net"), 0.95),
    ("Google Tag Manager", "script_asset", ("googletagmanager.com/gtm.js",), 0.96),
    ("Intercom", "script_asset", ("widget.intercom.io",), 0.95),
    ("Sentry", "script_asset", ("browser.sentry-cdn.com", "sentry.io"), 0.94),
    ("Datadog", "script_asset", ("datadoghq-browser-agent", "dd-rum"), 0.94),
    ("Cloudflare", "script_asset", ("challenges.cloudflare.com", "static.cloudflareinsights.com"), 0.94),
    ("AWS CloudFront / S3", "script_or_media_asset", ("cloudfront.net/", "s3.amazonaws.com/"), 0.90),
)

# 3. Low-Confidence Body Text Mention Rules (Suspected: 0.45 - 0.58)
# Prevents false positives when terms like "Kubernetes" or "AWS" only appear in prose/blog text
TEXT_MENTION_TECH_KEYWORDS: tuple[tuple[str, str, float], ...] = (
    ("Kubernetes", r"\b(kubernetes|k8s|eks|gke)\b", 0.52),
    ("Snowflake", r"\bsnowflake\b", 0.52),
    ("AWS CloudFront / S3", r"\b(amazonaws\.com|aws cloud|amazon web services)\b", 0.55),
    ("GraphQL", r"\b(graphql|apollo client)\b", 0.55),
    ("Salesforce", r"\b(salesforce|pardot)\b", 0.52),
    ("TypeScript", r"\btypescript\b", 0.50),
    ("Datadog", r"\bdatadog\b", 0.50),
)

JOB_TECH_KEYWORDS: tuple[str, ...] = (
    "Python",
    "TypeScript",
    "Go",
    "Rust",
    "Java",
    "React",
    "Next.js",
    "Node.js",
    "FastAPI",
    "Django",
    "PostgreSQL",
    "Snowflake",
    "Databricks",
    "Kafka",
    "Spark",
    "Kubernetes",
    "Docker",
    "Terraform",
    "AWS",
    "GCP",
    "Azure",
    "PyTorch",
    "LLM",
    "OpenAI",
    "LangChain",
    "GraphQL",
    "Redis",
    "dbt",
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify_tech_status(confidence_score: float) -> str:
    """Distinguish between 'confirmed' (sicher erkannt) and 'suspected' (vermutet)."""
    return "confirmed" if confidence_score >= CONFIRMED_THRESHOLD else "suspected"


def parse_tech_signals_detailed(
    html: str,
    headers: dict[str, str] | None = None,
    page_url: str = "",
    detected_at: str | None = None,
) -> list[dict[str, object]]:
    """Extract evidence-backed technology detections with confidence, signal source, timestamp, and status."""
    timestamp = detected_at or utc_now_iso()
    norm_headers = {k.lower(): str(v) for k, v in (headers or {}).items()}
    soup = BeautifulSoup(html, "html.parser")

    # Map: tech_name -> dict with highest confidence and aggregated signal sources
    detections: dict[str, dict[str, object]] = {}

    def _record_signal(name: str, confidence: float, source_desc: str) -> None:
        loc_suffix = f" @ {page_url}" if page_url else ""
        full_source = f"{source_desc}{loc_suffix}"
        existing = detections.get(name)
        if existing is None:
            detections[name] = {
                "name": name,
                "confidence_score": round(confidence, 2),
                "signal_sources": [full_source],
                "detected_at": timestamp,
            }
        else:
            sources_list: list[str] = list(existing["signal_sources"])  # type: ignore[arg-type]
            if full_source not in sources_list:
                sources_list.append(full_source)
            # Corroboration bonus (+0.04) when multiple distinct signals confirm the same technology
            base_conf = max(float(existing["confidence_score"]), confidence)  # type: ignore[arg-type]
            boosted = min(0.99, base_conf + (0.04 if len(sources_list) > 1 else 0.0))
            existing["confidence_score"] = round(boosted, 2)
            existing["signal_sources"] = sources_list

    # 1. Inspect HTTP response headers (high confidence: confirmed)
    for tech_name, hdr_key, val_regex, conf in HEADER_TECH_RULES:
        if hdr_key in norm_headers and re.search(val_regex, norm_headers[hdr_key], re.I):
            hdr_val = norm_headers[hdr_key][:40]
            _record_signal(tech_name, conf, f"http_header ({hdr_key}: {hdr_val})")

    # 2. Inspect <meta name="generator"> (high confidence: confirmed)
    generator = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
    if generator and generator.get("content"):
        gen_val = str(generator["content"]).strip()
        if gen_val:
            _record_signal(gen_val, 0.95, f"meta_generator ({gen_val})")

    # 3. Inspect <script>, <link>, <style>, and DOM structural attributes (high confidence: confirmed)
    asset_blobs: list[str] = []
    for s_tag in soup.find_all("script"):
        if s_tag.get("src"):
            asset_blobs.append(str(s_tag["src"]))
        if s_tag.get("id"):
            asset_blobs.append(f"id={s_tag['id']}")
        inline_code = (s_tag.string or "")[:600]
        if inline_code:
            asset_blobs.append(inline_code)

    for l_tag in soup.find_all(["link", "style"]):
        if l_tag.get("href"):
            asset_blobs.append(str(l_tag["href"]))
        inline_style = (l_tag.string or "")[:600]
        if inline_style:
            asset_blobs.append(inline_style)

    # Also check root/element attributes like data-reactroot, ng-version, data-v-*
    raw_opening_tags = " ".join(re.findall(r"<[a-zA-Z0-9-]+[^>]*>", html[:15000]))
    combined_asset_surface = f"{' '.join(asset_blobs)} {raw_opening_tags}".lower()

    for tech_name, category, patterns, conf in ASSET_AND_DOM_RULES:
        for pat in patterns:
            if pat.lower() in combined_asset_surface:
                _record_signal(tech_name, conf, f"{category} (matched '{pat}')")
                break

    # 4. Inspect plain body text mentions (low confidence: suspected, unless already confirmed above)
    visible_text = " ".join(soup.get_text(" ", strip=True).split())
    for tech_name, text_regex, low_conf in TEXT_MENTION_TECH_KEYWORDS:
        if tech_name not in detections and re.search(text_regex, visible_text, re.I):
            _record_signal(tech_name, low_conf, "body_text_mention")

    # Finalize serialized records sorted by confidence descending
    results: list[dict[str, object]] = []
    for item in detections.values():
        conf_val = float(item["confidence_score"])  # type: ignore[arg-type]
        srcs = list(item["signal_sources"])  # type: ignore[arg-type]
        results.append(
            {
                "name": str(item["name"]),
                "confidence_score": conf_val,
                "signal_source": "; ".join(srcs[:2]),
                "detected_at": str(item["detected_at"]),
                "detection_status": classify_tech_status(conf_val),
            }
        )

    results.sort(key=lambda r: (float(r["confidence_score"]), str(r["name"])), reverse=True)  # type: ignore[arg-type]
    return results


def parse_tech_signals_from_html(
    html: str, headers: dict[str, str] | None = None
) -> list[str]:
    """Return sorted list of detected technology names (backward-compatible helper)."""
    detailed = parse_tech_signals_detailed(html, headers=headers)
    return sorted({str(d["name"]) for d in detailed})


def parse_job_board_signals(
    html: str,
    page_url: str,
    detected_at: str | None = None,
    max_excerpt_chars: int = DEFAULT_SETTINGS.max_careers_excerpt_chars,
) -> dict[str, object]:
    """Extract open role titles and suspected engineering tech signals with GDPR data minimization."""
    timestamp = detected_at or utc_now_iso()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "footer", "nav"]):
        tag.decompose()
    strip_personal_dom_elements(soup)

    text_content = scrub_personal_data(" ".join(soup.get_text(" ", strip=True).split()))

    role_headings: list[str] = []
    role_regex = re.compile(
        r"(engineer|developer|architect|scientist|manager|lead|sre|devops|platform|security|data|ai|ml)",
        re.I,
    )
    for tag in soup.find_all(["h2", "h3", "h4", "a"], limit=60):
        label = scrub_personal_data(" ".join(tag.get_text(" ", strip=True).split()))
        if 6 <= len(label) <= 90 and role_regex.search(label) and label not in role_headings:
            role_headings.append(label)
            if len(role_headings) >= 10:
                break

    has_engineering_roles = len(role_headings) > 0
    matched_skills: list[str] = []
    job_tech_signals: list[dict[str, object]] = []

    for kw in JOB_TECH_KEYWORDS:
        pattern = rf"\b{re.escape(kw)}\b"
        matches = re.findall(pattern, text_content, flags=re.IGNORECASE)
        if matches:
            matched_skills.append(kw)
            # Job board mentions indicate probable internal usage ('suspected' until confirmed by runtime assets)
            base_conf = 0.72 if has_engineering_roles else 0.60
            freq_bonus = min(0.06, (len(matches) - 1) * 0.02)
            conf = round(min(0.78, base_conf + freq_bonus), 2)
            job_tech_signals.append(
                {
                    "name": kw,
                    "confidence_score": conf,
                    "signal_source": f"job_posting_requirement ({page_url})",
                    "detected_at": timestamp,
                    "detection_status": classify_tech_status(conf),
                }
            )

    return {
        "careers_url": page_url,
        "detected_at": timestamp,
        "detected_job_skills": matched_skills,
        "technology_signals": job_tech_signals,
        "open_role_signals": role_headings,
        "excerpt": text_content[:max_excerpt_chars],
    }


async def detect_website_tech_stack_impl(
    url: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Fetch a target website via SSRF-safe GET and fingerprint its web, analytics, and cloud stack."""
    normalized_url = normalize_target_url(url)
    timestamp = utc_now_iso()
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=False, timeout=timeout
    ) as client:
        try:
            response = await safe_http_get(normalized_url, client)
            headers_dict = {k.lower(): v for k, v in response.headers.items()}
            final_url = str(response.url)
            detailed = parse_tech_signals_detailed(
                response.text,
                headers=headers_dict,
                page_url=final_url,
                detected_at=timestamp,
            )
            confirmed_names = [
                str(d["name"]) for d in detailed if d["detection_status"] == "confirmed"
            ]
            suspected_names = [
                str(d["name"]) for d in detailed if d["detection_status"] == "suspected"
            ]
            return {
                "url": final_url,
                "detected_at": timestamp,
                "detected_technologies": [str(d["name"]) for d in detailed],
                "confirmed_technologies": confirmed_names,
                "suspected_technologies": suspected_names,
                "technology_signals": detailed,
                "server_header": headers_dict.get("server", "unknown"),
                "powered_by": headers_dict.get("x-powered-by", "unknown"),
            }
        except (httpx.HTTPError, SSRFBlockedError) as exc:
            return {
                "url": normalized_url,
                "detected_at": timestamp,
                "detected_technologies": [],
                "confirmed_technologies": [],
                "suspected_technologies": [],
                "technology_signals": [],
                "error": f"Tech detection HTTP warning: {exc!s}",
            }


async def scrape_careers_and_job_postings_impl(
    url: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Scan common careers/jobs paths on the company domain via SSRF-safe GET to infer backend tech stack."""
    normalized_url = normalize_target_url(url)
    parsed = urlparse(normalized_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else normalized_url

    career_paths = ["/careers", "/jobs", "/company/careers", "/about/careers"]
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=False, timeout=timeout
    ) as client:
        for path in career_paths:
            candidate_url = urljoin(base_origin, path)
            try:
                resp = await safe_http_get(candidate_url, client)
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    parsed_jobs = parse_job_board_signals(resp.text, str(resp.url))
                    if parsed_jobs["detected_job_skills"] or parsed_jobs["open_role_signals"]:
                        return parsed_jobs
            except (httpx.HTTPError, SSRFBlockedError):
                continue

        # Fallback: inspect homepage for careers links or embedded tech keywords
        try:
            home_resp = await safe_http_get(normalized_url, client)
            return parse_job_board_signals(home_resp.text, str(home_resp.url))
        except (httpx.HTTPError, SSRFBlockedError) as exc:
            return {
                "careers_url": normalized_url,
                "detected_at": utc_now_iso(),
                "detected_job_skills": [],
                "technology_signals": [],
                "open_role_signals": [],
                "error": f"Careers scan warning: {exc!s}",
            }


@function_tool
async def detect_website_tech_stack(
    ctx: RunContextWrapper[LeadRunContext], url: str
) -> str:
    """Inspect HTTP headers, script tags, and HTML metadata to detect a company's tech stack with confidence scores.

    Args:
        url: Target company domain or URL.
    """
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        ctx.context.log_tool_event(f"Tech-Stack Agent -> detect_website_tech_stack({url})")
    result = await detect_website_tech_stack_impl(url)
    return json.dumps(result, ensure_ascii=False)


@function_tool
async def scrape_careers_and_job_postings(
    ctx: RunContextWrapper[LeadRunContext], url: str
) -> str:
    """Scan the company's careers/job pages to infer backend stack and hiring priorities with confidence scores.

    Args:
        url: Target company domain or URL.
    """
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        ctx.context.log_tool_event(f"Tech-Stack Agent -> scrape_careers_and_job_postings({url})")
    result = await scrape_careers_and_job_postings_impl(url)
    return json.dumps(result, ensure_ascii=False)
