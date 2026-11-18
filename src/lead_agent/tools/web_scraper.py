"""Web and news scraping tools for the Company & News Agent."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

try:
    from agents import RunContextWrapper, function_tool
except ImportError:  # pragma: no cover - fallback when SDK is not yet installed
    RunContextWrapper = object  # type: ignore[misc,assignment]

    def function_tool(func=None, **_kwargs):  # type: ignore[no-redef]
        if func is None:
            return lambda f: f
        return func


from lead_agent.config import DEFAULT_SETTINGS
from lead_agent.context import LeadRunContext

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_target_url(raw_input: str) -> str:
    """Normalize a raw domain or URL into an HTTPS URL."""
    cleaned = raw_input.strip()
    if not cleaned:
        raise ValueError("Target URL or domain cannot be empty.")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    return cleaned


def extract_clean_page_data(html: str, base_url: str, max_chars: int = 6000) -> dict[str, object]:
    """Parse HTML into structured title, meta description, headings, news links, and body snippet."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "footer", "nav"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta_tag and meta_tag.get("content"):
        meta_desc = str(meta_tag.get("content")).strip()

    headings: list[str] = []
    for h_tag in soup.find_all(["h1", "h2", "h3"], limit=15):
        text = " ".join(h_tag.get_text(" ", strip=True).split())
        if text and text not in headings:
            headings.append(text)

    news_links: list[dict[str, str]] = []
    news_pattern = re.compile(r"(news|press|blog|release|announcement|about|investor|quarterly)", re.I)
    for a_tag in soup.find_all("a", href=True):
        href = str(a_tag["href"]).strip()
        label = " ".join(a_tag.get_text(" ", strip=True).split())
        if news_pattern.search(href) or news_pattern.search(label):
            full_url = urljoin(base_url, href)
            if full_url.startswith(("http://", "https://")) and len(news_links) < 8:
                news_links.append({"title": label or "Company Update Page", "url": full_url})

    body_text = " ".join(soup.get_text(" ", strip=True).split())
    return {
        "url": base_url,
        "title": title,
        "meta_description": meta_desc,
        "headings": headings,
        "discovered_news_links": news_links,
        "body_excerpt": body_text[:max_chars],
    }


async def scrape_company_website_impl(
    url: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Fetch a company webpage and extract clean structured content."""
    normalized_url = normalize_target_url(url)
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        try:
            response = await client.get(normalized_url)
            response.raise_for_status()
            return extract_clean_page_data(
                response.text,
                str(response.url),
                max_chars=DEFAULT_SETTINGS.max_scrape_chars,
            )
        except httpx.HTTPError as exc:
            return {
                "url": normalized_url,
                "error": f"HTTP fetch warning: {exc!s}",
                "title": urlparse(normalized_url).netloc,
                "meta_description": "",
                "headings": [],
                "discovered_news_links": [],
                "body_excerpt": "",
            }


async def fetch_company_news_and_press_impl(
    company_or_domain: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Discover press releases, blog posts, and public news items for a target company."""
    normalized_url = normalize_target_url(company_or_domain)
    parsed = urlparse(normalized_url)
    domain = parsed.netloc or company_or_domain.strip()
    base_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else normalized_url

    articles: list[dict[str, str]] = []
    candidate_paths = ["/news", "/press", "/blog", "/about"]

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        for path in candidate_paths:
            target = urljoin(base_origin, path)
            try:
                resp = await client.get(target)
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    page_data = extract_clean_page_data(resp.text, str(resp.url), max_chars=2500)
                    articles.append(
                        {
                            "title": str(page_data["title"] or f"{domain} {path.strip('/')} page"),
                            "url": str(resp.url),
                            "snippet": str(page_data["body_excerpt"])[:500],
                        }
                    )
                    if len(articles) >= 3:
                        break
            except httpx.HTTPError:
                continue

    if not articles:
        articles.append(
            {
                "title": f"{domain} Official Website",
                "url": normalized_url,
                "snippet": f"Primary corporate domain for {domain}.",
            }
        )

    return {
        "company_or_domain": domain,
        "articles_found": len(articles),
        "articles": articles,
    }


@function_tool
async def scrape_company_website(
    ctx: RunContextWrapper[LeadRunContext], url: str
) -> str:
    """Scrape a company's website homepage or LinkedIn URL for overview, positioning, and headings.

    Args:
        url: The domain (e.g. 'stripe.com') or full URL to scrape.
    """
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        ctx.context.log_tool_event(f"Company & News Agent -> scrape_company_website({url})")
    data = await scrape_company_website_impl(url)
    return json.dumps(data, ensure_ascii=False)


@function_tool
async def fetch_company_news_and_press(
    ctx: RunContextWrapper[LeadRunContext], company_or_domain: str
) -> str:
    """Fetch recent press releases, newsroom updates, and blog announcements for a company.

    Args:
        company_or_domain: Target domain or company URL to scan for news and triggers.
    """
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        ctx.context.log_tool_event(
            f"Company & News Agent -> fetch_company_news_and_press({company_or_domain})"
        )
    data = await fetch_company_news_and_press_impl(company_or_domain)
    return json.dumps(data, ensure_ascii=False)

