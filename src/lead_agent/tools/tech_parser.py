"""Tech-stack and job-board HTML parsing tools for the Tech-Stack Agent."""

from __future__ import annotations

import json
import re
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
from lead_agent.tools.web_scraper import DEFAULT_HEADERS, normalize_target_url

# Signatures for HTML / script / header tech-stack fingerprinting
TECH_SIGNATURES: dict[str, tuple[str, ...]] = {
    "Next.js": ("_next/static", "__NEXT_DATA__", "next-head"),
    "React": ("react-dom", "data-reactroot", "__REACT"),
    "Vue.js": ("vue.runtime", "vue.global", "data-v-"),
    "Angular": ("ng-version", "angular.min.js"),
    "Tailwind CSS": ("tailwindcss", "--tw-"),
    "TypeScript": ("typescript", ".ts"),
    "GraphQL": ("graphql", "__typename", "apollo"),
    "Stripe": ("js.stripe.com", "stripe-js"),
    "Segment": ("cdn.segment.com", "analytics.load"),
    "HubSpot": ("js.hs-scripts.com", "hs-analytics", "hubspot"),
    "Salesforce": ("salesforce", "pardot", "sfdc"),
    "Google Tag Manager": ("googletagmanager.com/gtm.js",),
    "Intercom": ("widget.intercom.io", "Intercom("),
    "Cloudflare": ("cf-ray", "cloudflare", "__cf_bm"),
    "AWS CloudFront / S3": ("cloudfront.net", "amazonaws.com", "x-amz-"),
    "Vercel": ("x-vercel-id", "vercel.app"),
    "Sentry": ("browser.sentry-cdn.com", "sentry.io"),
    "Datadog": ("datadoghq", "dd-rum"),
    "Snowflake": ("snowflake",),
    "Kubernetes": ("kubernetes", "k8s", "eks", "gke"),
}

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


def parse_tech_signals_from_html(
    html: str, headers: dict[str, str] | None = None
) -> list[str]:
    """Identify frontend, cloud, analytics, and infrastructure technologies from HTML & headers."""
    combined_headers = " ".join(
        f"{k}: {v}" for k, v in (headers or {}).items()
    ).lower()
    lower_html = html.lower()

    detected: list[str] = []
    for tech_name, patterns in TECH_SIGNATURES.items():
        for pat in patterns:
            pat_lower = pat.lower()
            if pat_lower in lower_html or pat_lower in combined_headers:
                detected.append(tech_name)
                break

    soup = BeautifulSoup(html, "html.parser")
    generator = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
    if generator and generator.get("content"):
        gen_val = str(generator["content"]).strip()
        if gen_val and gen_val not in detected:
            detected.append(gen_val)

    return sorted(set(detected))


def parse_job_board_signals(html: str, page_url: str) -> dict[str, object]:
    """Extract open role titles and mentioned engineering skills from a careers/job HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    text_content = " ".join(soup.get_text(" ", strip=True).split())

    matched_skills: list[str] = []
    for kw in JOB_TECH_KEYWORDS:
        pattern = rf"\b{re.escape(kw)}\b"
        if re.search(pattern, text_content, flags=re.IGNORECASE):
            matched_skills.append(kw)

    role_headings: list[str] = []
    role_regex = re.compile(
        r"(engineer|developer|architect|scientist|manager|lead|sre|devops|platform|security|data|ai|ml)",
        re.I,
    )
    for tag in soup.find_all(["h2", "h3", "h4", "a"], limit=60):
        label = " ".join(tag.get_text(" ", strip=True).split())
        if 6 <= len(label) <= 90 and role_regex.search(label) and label not in role_headings:
            role_headings.append(label)
            if len(role_headings) >= 10:
                break

    return {
        "careers_url": page_url,
        "detected_job_skills": matched_skills,
        "open_role_signals": role_headings,
        "excerpt": text_content[:2000],
    }


async def detect_website_tech_stack_impl(
    url: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Fetch a target website and fingerprint its web, analytics, and cloud stack."""
    normalized_url = normalize_target_url(url)
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        try:
            response = await client.get(normalized_url)
            headers_dict = {k.lower(): v for k, v in response.headers.items()}
            detected = parse_tech_signals_from_html(response.text, headers_dict)
            return {
                "url": str(response.url),
                "detected_technologies": detected,
                "server_header": headers_dict.get("server", "unknown"),
                "powered_by": headers_dict.get("x-powered-by", "unknown"),
            }
        except httpx.HTTPError as exc:
            return {
                "url": normalized_url,
                "detected_technologies": [],
                "error": f"Tech detection HTTP warning: {exc!s}",
            }


async def scrape_careers_and_job_postings_impl(
    url: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Scan common careers/jobs paths on the company domain to infer backend tech stack."""
    normalized_url = normalize_target_url(url)
    parsed = urlparse(normalized_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else normalized_url

    career_paths = ["/careers", "/jobs", "/company/careers", "/about/careers"]
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        for path in career_paths:
            candidate_url = urljoin(base_origin, path)
            try:
                resp = await client.get(candidate_url)
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    parsed_jobs = parse_job_board_signals(resp.text, str(resp.url))
                    if parsed_jobs["detected_job_skills"] or parsed_jobs["open_role_signals"]:
                        return parsed_jobs
            except httpx.HTTPError:
                continue

        # Fallback: inspect homepage for careers links or embedded tech keywords
        try:
            home_resp = await client.get(normalized_url)
            return parse_job_board_signals(home_resp.text, str(home_resp.url))
        except httpx.HTTPError as exc:
            return {
                "careers_url": normalized_url,
                "detected_job_skills": [],
                "open_role_signals": [],
                "error": f"Careers scan warning: {exc!s}",
            }


@function_tool
async def detect_website_tech_stack(
    ctx: RunContextWrapper[LeadRunContext], url: str
) -> str:
    """Inspect HTTP headers, script tags, and HTML metadata to detect a company's tech stack.

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
    """Scan the company's careers/job pages to infer backend stack and hiring priorities.

    Args:
        url: Target company domain or URL.
    """
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        ctx.context.log_tool_event(f"Tech-Stack Agent -> scrape_careers_and_job_postings({url})")
    result = await scrape_careers_and_job_postings_impl(url)
    return json.dumps(result, ensure_ascii=False)

