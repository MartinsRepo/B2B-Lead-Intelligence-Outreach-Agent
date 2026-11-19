"""Web and multi-source news scraping tools for the Company & News Agent."""

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
from lead_agent.security import SSRFBlockedError, safe_http_get, validate_url_ssrf
from lead_agent.tools.research_engine import (
    EvaluatedSource,
    deduplicate_and_rank_sources,
    discover_rss_feed_urls,
    evaluate_source_quality,
    extract_json_ld_and_hydration_state,
    fetch_external_google_news_rss,
    fetch_js_reader_fallback,
    parse_rss_or_atom_xml,
    serialize_evaluated_sources,
)

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
    """Parse HTML (plus JSON-LD, hydration state, and RSS feeds) into structured content."""
    # Extract structured JSON-LD & SPA hydration state before stripping <script> tags
    structured_state = extract_json_ld_and_hydration_state(html)
    rss_feeds = discover_rss_feed_urls(html, base_url)

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

    # Enrich headings with JSON-LD headlines if present on JS-heavy sites
    for ld_item in structured_state.get("json_ld_items", []):  # type: ignore[union-attr]
        if isinstance(ld_item, dict):
            hl = str(ld_item.get("headline", "")).strip()
            if hl and hl not in headings and len(headings) < 18:
                headings.append(hl)

    news_links: list[dict[str, str]] = []
    seen_news_urls: set[str] = set()
    news_pattern = re.compile(
        r"(news|newsroom|press|media|blog|release|announcement|stories|insight|investor|quarterly)",
        re.I,
    )
    for a_tag in soup.find_all("a", href=True):
        href = str(a_tag["href"]).strip()
        label = " ".join(a_tag.get_text(" ", strip=True).split())
        if news_pattern.search(href) or news_pattern.search(label):
            full_url = urljoin(base_url, href)
            if (
                full_url not in seen_news_urls
                and len(news_links) < 10
                and validate_url_ssrf(full_url, resolve_dns=False).is_safe
            ):
                seen_news_urls.add(full_url)
                news_links.append({"title": label or "Company Update Page", "url": full_url})

    body_text = " ".join(soup.get_text(" ", strip=True).split())

    # If static body text is thin, append hydration & JSON-LD descriptions
    hydration_parts: list[str] = []
    for ld_item in structured_state.get("json_ld_items", []):  # type: ignore[union-attr]
        if isinstance(ld_item, dict) and ld_item.get("description"):
            hydration_parts.append(str(ld_item["description"]))
    for hyd_text in structured_state.get("hydration_snippets", []):  # type: ignore[union-attr]
        if isinstance(hyd_text, str) and hyd_text not in body_text:
            hydration_parts.append(hyd_text)

    if hydration_parts:
        combined_body = f"{body_text} | {' '.join(hydration_parts)}".strip(" |")
    else:
        combined_body = body_text

    published_dates = structured_state.get("published_dates", [])
    updated_dates = structured_state.get("updated_dates", [])
    first_pub = str(published_dates[0]) if isinstance(published_dates, list) and published_dates else ""
    first_upd = str(updated_dates[0]) if isinstance(updated_dates, list) and updated_dates else ""

    return {
        "url": base_url,
        "title": title,
        "meta_description": meta_desc,
        "published_date": first_pub,
        "updated_date": first_upd,
        "headings": headings,
        "discovered_news_links": news_links,
        "discovered_rss_feeds": rss_feeds,
        "json_ld_items": structured_state.get("json_ld_items", []),
        "body_excerpt": combined_body[:max_chars],
    }


async def scrape_company_website_impl(
    url: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Fetch a company webpage with SSRF/redirect checks, JSON-LD/hydration recovery, and JS reader fallback."""
    normalized_url = normalize_target_url(url)
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=False, timeout=timeout
    ) as client:
        try:
            response = await safe_http_get(normalized_url, client)
            response.raise_for_status()
            page_data = extract_clean_page_data(
                response.text,
                str(response.url),
                max_chars=DEFAULT_SETTINGS.max_scrape_chars,
            )

            # JS-heavy SPA fallback: if static + hydrated text is still very thin (<250 chars)
            body_excerpt = str(page_data.get("body_excerpt", ""))
            if len(body_excerpt) < 250:
                rendered_text = await fetch_js_reader_fallback(
                    str(response.url), client, max_chars=DEFAULT_SETTINGS.max_scrape_chars
                )
                if rendered_text:
                    page_data["body_excerpt"] = rendered_text
                    page_data["js_reader_fallback_used"] = True

            evaluated = evaluate_source_quality(
                title=str(page_data.get("title") or urlparse(normalized_url).netloc),
                url=str(page_data.get("url") or normalized_url),
                snippet=str(page_data.get("meta_description") or page_data.get("body_excerpt", ""))[:450],
                target_domain=normalized_url,
                source_type="corporate_website",
                published_date=str(page_data.get("published_date", "")),
                updated_date=str(page_data.get("updated_date", "")),
            )
            page_data["source_evaluation"] = {
                "source_type": evaluated.source_type,
                "published_date": evaluated.published_date,
                "updated_date": evaluated.updated_date,
                "age_days": evaluated.age_days,
                "recency_score": evaluated.recency_score,
                "credibility_score": evaluated.credibility_score,
                "source_quality_score": evaluated.source_quality_score,
                "statement_quality_score": evaluated.statement_quality_score,
                "relevance_score": evaluated.relevance_score,
                "composite_score": evaluated.composite_score,
            }
            return page_data
        except (httpx.HTTPError, SSRFBlockedError) as exc:
            return {
                "url": normalized_url,
                "error": f"HTTP fetch warning: {exc!s}",
                "title": urlparse(normalized_url).netloc,
                "meta_description": "",
                "headings": [],
                "discovered_news_links": [],
                "discovered_rss_feeds": [],
                "body_excerpt": "",
            }


async def fetch_company_news_and_press_impl(
    company_or_domain: str, timeout: float = DEFAULT_SETTINGS.http_timeout_seconds
) -> dict[str, object]:
    """Multi-source news & press release engine combining 4 channels with source quality scoring:

    1. Homepage news-link & RSS/Atom feed auto-discovery
    2. Corporate newsroom & press release subpages (/newsroom, /press, /news, /blog)
    3. Deep article crawling of discovered internal press links
    4. External Google News RSS search for third-party coverage & press wires
    """
    normalized_url = normalize_target_url(company_or_domain)
    parsed = urlparse(normalized_url)
    domain = (parsed.netloc or company_or_domain.strip()).removeprefix("www.")
    company_name_query = domain.split(".")[0].replace("-", " ").title()
    base_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else normalized_url

    evaluated_sources: list[EvaluatedSource] = []
    discovered_sublinks: list[str] = []
    rss_feed_urls: list[str] = []

    candidate_paths = [
        "/newsroom",
        "/press",
        "/news",
        "/blog",
        "/en/press",
        "/company/news",
        "/about",
    ]
    candidate_rss_paths = ["/feed", "/rss.xml", "/blog/rss.xml", "/news/rss.xml"]

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=False, timeout=timeout
    ) as client:
        # Step 1: Inspect homepage for embedded news links, JSON-LD articles, and RSS feed links
        try:
            home_resp = await safe_http_get(normalized_url, client)
            if home_resp.status_code == 200:
                home_data = extract_clean_page_data(
                    home_resp.text, str(home_resp.url), max_chars=2500
                )
                for link_obj in home_data.get("discovered_news_links", []):  # type: ignore[union-attr]
                    if isinstance(link_obj, dict) and link_obj.get("url"):
                        discovered_sublinks.append(str(link_obj["url"]))
                for feed_url in home_data.get("discovered_rss_feeds", []):  # type: ignore[union-attr]
                    if isinstance(feed_url, str) and feed_url not in rss_feed_urls:
                        rss_feed_urls.append(feed_url)
        except (httpx.HTTPError, SSRFBlockedError):
            pass

        # Step 2: Check discovered RSS/Atom feeds + common RSS endpoints
        for r_path in candidate_rss_paths:
            candidate_feed = urljoin(base_origin, r_path)
            if candidate_feed not in rss_feed_urls and len(rss_feed_urls) < 4:
                rss_feed_urls.append(candidate_feed)

        for feed_url in rss_feed_urls[:3]:
            try:
                f_resp = await safe_http_get(feed_url, client, timeout=6.0)
                if f_resp.status_code == 200 and (
                    "<rss" in f_resp.text[:500].lower() or "<feed" in f_resp.text[:500].lower()
                ):
                    feed_items = parse_rss_or_atom_xml(f_resp.text, default_source_type="rss_feed")
                    for item in feed_items[:4]:
                        evaluated_sources.append(
                            evaluate_source_quality(
                                title=item["title"],
                                url=item["url"],
                                snippet=item["snippet"],
                                target_domain=domain,
                                source_type="rss_feed",
                                published_date=item.get("published_date", ""),
                                updated_date=item.get("updated_date", ""),
                            )
                        )
                    if len(evaluated_sources) >= 4:
                        break
            except (httpx.HTTPError, SSRFBlockedError):
                continue

        # Step 3: Crawl corporate newsroom / press subpages and discovered news links
        targets_to_crawl: list[str] = []
        for d_url in discovered_sublinks[:4]:
            if d_url not in targets_to_crawl:
                targets_to_crawl.append(d_url)
        for path in candidate_paths:
            p_url = urljoin(base_origin, path)
            if p_url not in targets_to_crawl:
                targets_to_crawl.append(p_url)

        for target in targets_to_crawl[:6]:
            try:
                resp = await safe_http_get(target, client, timeout=8.0)
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    page_data = extract_clean_page_data(resp.text, str(resp.url), max_chars=2500)
                    snippet_text = str(
                        page_data.get("meta_description") or page_data.get("body_excerpt", "")
                    )[:500]
                    headings_preview = "; ".join(
                        str(h) for h in (page_data.get("headings") or [])[:4]  # type: ignore[union-attr]
                    )
                    rich_snippet = (
                        f"{headings_preview} — {snippet_text}".strip(" —")
                        if headings_preview
                        else snippet_text
                    )
                    evaluated_sources.append(
                        evaluate_source_quality(
                            title=str(page_data["title"] or f"{domain} News & Press"),
                            url=str(resp.url),
                            snippet=rich_snippet[:500],
                            target_domain=domain,
                            source_type="official_newsroom",
                            published_date=str(page_data.get("published_date", "")),
                            updated_date=str(page_data.get("updated_date", "")),
                        )
                    )
                    if len(evaluated_sources) >= 6:
                        break
            except (httpx.HTTPError, SSRFBlockedError):
                continue

        # Step 4: Fetch external news coverage & press releases via Google News RSS
        external_articles = await fetch_external_google_news_rss(
            f'"{company_name_query}" OR "{domain}"', client
        )
        for ext in external_articles[:4]:
            evaluated_sources.append(
                evaluate_source_quality(
                    title=ext["title"],
                    url=ext["url"],
                    snippet=ext["snippet"],
                    target_domain=domain,
                    source_type="external_news",
                    published_date=ext.get("published_date", ""),
                    updated_date=ext.get("updated_date", ""),
                )
            )

    if not evaluated_sources:
        evaluated_sources.append(
            evaluate_source_quality(
                title=f"{domain} Official Corporate Website",
                url=normalized_url,
                snippet=f"Primary corporate domain and product overview for {domain}.",
                target_domain=domain,
                source_type="corporate_website",
            )
        )

    ranked_sources = deduplicate_and_rank_sources(evaluated_sources, max_results=8)
    serialized = serialize_evaluated_sources(ranked_sources)

    return {
        "company_or_domain": domain,
        "channels_combined": [
            "corporate_newsroom_crawler",
            "rss_atom_feed_discovery",
            "json_ld_and_spa_hydration_extractor",
            "external_google_news_rss",
        ],
        "articles_found": len(serialized),
        "average_composite_score": round(
            sum(s.composite_score for s in ranked_sources) / max(len(ranked_sources), 1), 2
        ),
        "articles": serialized,
    }


@function_tool
async def scrape_company_website(
    ctx: RunContextWrapper[LeadRunContext], url: str
) -> str:
    """Scrape a company's website with JSON-LD/hydration state extraction and JS reader fallback.

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
    """Multi-source research tool combining newsrooms, RSS/Atom feeds, JSON-LD, and external news with source quality scores.

    Args:
        company_or_domain: Target domain or company URL to scan for news, press releases, and scored sources.
    """
    if hasattr(ctx, "context") and isinstance(ctx.context, LeadRunContext):
        ctx.context.log_tool_event(
            f"Company & News Agent -> fetch_company_news_and_press({company_or_domain})"
        )
    data = await fetch_company_news_and_press_impl(company_or_domain)
    return json.dumps(data, ensure_ascii=False)
