"""Multi-source B2B research engine with JS state extraction and source quality scoring."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from lead_agent.config import DEFAULT_SETTINGS

TIER1_NEWS_DOMAINS: tuple[str, ...] = (
    "prnewswire.com",
    "businesswire.com",
    "globenewswire.com",
    "reuters.com",
    "bloomberg.com",
    "techcrunch.com",
    "wsj.com",
    "ft.com",
    "forbes.com",
    "cnbc.com",
    "handelsblatt.com",
    "heise.de",
    "venturebeat.com",
)

B2B_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "launch",
    "launches",
    "launched",
    "announces",
    "announced",
    "release",
    "releases",
    "partnership",
    "partners",
    "funding",
    "series",
    "acquisition",
    "acquires",
    "quarterly",
    "revenue",
    "growth",
    "enterprise",
    "platform",
    "ai",
    "cloud",
    "expansion",
    "milestone",
    "report",
    "new",
)


@dataclass
class EvaluatedSource:
    """A discovered research source enriched with credibility, relevance, and recency scores."""

    title: str
    url: str
    snippet: str
    source_type: str  # "official_newsroom" | "press_release" | "external_news" | "rss_feed" | "corporate_website"
    published_date: str = ""
    credibility_score: float = 0.8
    relevance_score: float = 0.8
    composite_score: float = 0.8


def extract_json_ld_and_hydration_state(html: str) -> dict[str, object]:
    """Extract structured data from JSON-LD (<script type='application/ld+json'>) and Next.js/__NEXT_DATA__.

    Helps recover rich content and article metadata on JavaScript-heavy / SPA corporate websites.
    """
    soup = BeautifulSoup(html, "html.parser")
    json_ld_items: list[dict[str, str]] = []
    hydration_snippets: list[str] = []
    published_dates: list[str] = []

    # 1. Parse JSON-LD blocks
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw_text = (script.string or script.get_text() or "").strip()
        if not raw_text:
            continue
        try:
            parsed = json.loads(raw_text)
            nodes = parsed if isinstance(parsed, list) else [parsed]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                graph = node.get("@graph")
                subnodes = graph if isinstance(graph, list) else [node]
                for item in subnodes:
                    if not isinstance(item, dict):
                        continue
                    headline = str(
                        item.get("headline") or item.get("name") or ""
                    ).strip()
                    desc = str(
                        item.get("description") or item.get("articleBody") or ""
                    ).strip()
                    date_pub = str(
                        item.get("datePublished") or item.get("dateModified") or ""
                    ).strip()
                    if date_pub and date_pub not in published_dates:
                        published_dates.append(date_pub[:10])
                    if headline or desc:
                        json_ld_items.append(
                            {
                                "type": str(item.get("@type", "Thing")),
                                "headline": headline,
                                "description": desc[:600],
                                "date": date_pub[:10],
                            }
                        )
        except Exception:
            continue

    # 2. Parse Next.js / Nuxt hydration JSON payloads (__NEXT_DATA__)
    next_data_tag = soup.find("script", attrs={"id": "__NEXT_DATA__"})
    if next_data_tag:
        raw_next = (next_data_tag.string or next_data_tag.get_text() or "").strip()
        if raw_next:
            try:
                next_obj = json.loads(raw_next)
                extracted_strings: list[str] = []
                _collect_informative_strings(next_obj, extracted_strings, max_items=20)
                hydration_snippets.extend(extracted_strings)
            except Exception:
                pass

    # 3. Check OpenGraph / article published time meta tags
    date_meta = soup.find(
        "meta",
        attrs={
            "property": re.compile(r"(article:published_time|og:updated_time)", re.I)
        },
    ) or soup.find("meta", attrs={"name": re.compile(r"(date|pubdate|publish-date)", re.I)})
    if date_meta and date_meta.get("content"):
        d_str = str(date_meta["content"]).strip()[:10]
        if d_str and d_str not in published_dates:
            published_dates.append(d_str)

    return {
        "json_ld_items": json_ld_items[:10],
        "hydration_snippets": hydration_snippets[:12],
        "published_dates": published_dates[:5],
    }


def _collect_informative_strings(
    node: object, acc: list[str], max_items: int = 20
) -> None:
    """Recursively collect human-readable sentences from a hydration JSON tree."""
    if len(acc) >= max_items:
        return
    if isinstance(node, str):
        cleaned = " ".join(node.split())
        # Keep strings that look like natural language sentences/headlines (not URLs or hashes)
        if (
            35 <= len(cleaned) <= 450
            and " " in cleaned
            and not cleaned.startswith(("http://", "https://", "/", "{", "["))
            and cleaned not in acc
        ):
            acc.append(cleaned)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.lower() in {"title", "headline", "summary", "description", "excerpt", "subtitle", "text"}:
                _collect_informative_strings(v, acc, max_items=max_items)
            elif isinstance(v, (dict, list)):
                _collect_informative_strings(v, acc, max_items=max_items)
    elif isinstance(node, list):
        for item in node[:15]:
            _collect_informative_strings(item, acc, max_items=max_items)


def discover_rss_feed_urls(html: str, base_url: str) -> list[str]:
    """Discover RSS or Atom feed links embedded in a webpage's HTML."""
    soup = BeautifulSoup(html, "html.parser")
    feeds: list[str] = []
    for link in soup.find_all("link", href=True):
        link_type = str(link.get("type", "")).lower()
        href = str(link["href"]).strip()
        if "rss" in link_type or "atom" in link_type or "xml" in link_type or href.endswith((".rss", "/feed", "/feed/", "/rss.xml", "/atom.xml")):
            full = urljoin(base_url, href)
            if full.startswith(("http://", "https://")) and full not in feeds:
                feeds.append(full)
    return feeds[:4]


def parse_rss_or_atom_xml(xml_text: str, default_source_type: str = "rss_feed") -> list[dict[str, str]]:
    """Parse standard RSS 2.0 or Atom XML feeds into structured article dictionaries."""
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return items

    # RSS 2.0 <item> elements
    for item in root.findall(".//item")[:8]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc_raw = (item.findtext("description") or "").strip()
        pub_date = _normalize_date_string((item.findtext("pubDate") or "").strip())
        clean_desc = " ".join(BeautifulSoup(desc_raw, "html.parser").get_text(" ", strip=True).split())
        if title and link.startswith(("http://", "https://")):
            items.append(
                {
                    "title": title,
                    "url": link,
                    "snippet": (clean_desc or title)[:500],
                    "published_date": pub_date,
                    "source_type": default_source_type,
                }
            )

    # Atom <entry> elements
    if not items:
        for entry in root.findall(".//{*}entry")[:8]:
            title = ""
            link = ""
            summary = ""
            pub_date = ""
            for child in entry:
                tag_name = child.tag.split("}")[-1].lower()
                if tag_name == "title" and child.text:
                    title = child.text.strip()
                elif tag_name == "link":
                    href = child.attrib.get("href", "").strip()
                    if href:
                        link = href
                elif tag_name in {"summary", "content"} and child.text:
                    summary = " ".join(
                        BeautifulSoup(child.text, "html.parser").get_text(" ", strip=True).split()
                    )
                elif tag_name in {"published", "updated"} and child.text and not pub_date:
                    pub_date = _normalize_date_string(child.text.strip())
            if title and link.startswith(("http://", "https://")):
                items.append(
                    {
                        "title": title,
                        "url": link,
                        "snippet": (summary or title)[:500],
                        "published_date": pub_date,
                        "source_type": default_source_type,
                    }
                )

    return items


def _normalize_date_string(raw_date: str) -> str:
    """Convert RFC-2822 or ISO date strings into YYYY-MM-DD when possible."""
    if not raw_date:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw_date):
        return raw_date[:10]
    try:
        dt = parsedate_to_datetime(raw_date)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return raw_date[:16]


def evaluate_source_quality(
    title: str,
    url: str,
    snippet: str,
    target_domain: str,
    source_type: str = "corporate_website",
    published_date: str = "",
) -> EvaluatedSource:
    """Compute deterministic credibility, relevance, and composite quality scores (0.0 - 1.0)."""
    parsed_url = urlparse(url)
    source_host = (parsed_url.hostname or "").lower().removeprefix("www.")
    clean_target = (
        urlparse(target_domain if "://" in target_domain else f"https://{target_domain}").hostname
        or target_domain
    ).lower().removeprefix("www.")
    company_token = clean_target.split(".")[0]

    # 1. Credibility Score (Provenance & Authority)
    if clean_target and (source_host == clean_target or source_host.endswith(f".{clean_target}")):
        if source_type in {"official_newsroom", "press_release", "rss_feed"} or any(
            p in parsed_url.path.lower() for p in ("/news", "/press", "/blog", "/releases")
        ):
            credibility = 0.96
            if source_type == "corporate_website":
                source_type = "official_newsroom"
        else:
            credibility = 0.90
    elif any(source_host == d or source_host.endswith(f".{d}") for d in TIER1_NEWS_DOMAINS):
        credibility = 0.92
        source_type = "press_release" if "wire" in source_host else "external_news"
    elif "news.google.com" in source_host:
        credibility = 0.85
        source_type = "external_news"
    elif parsed_url.scheme == "https":
        credibility = 0.75
    else:
        credibility = 0.55

    # 2. Relevance Score (Company mention + B2B trigger density + snippet substance)
    combined_text = f"{title} {snippet}".lower()
    trigger_hits = sum(1 for kw in B2B_TRIGGER_KEYWORDS if re.search(rf"\b{kw}\b", combined_text))
    has_company_mention = bool(company_token and company_token in combined_text) or (
        clean_target in source_host
    )

    relevance = 0.55
    if has_company_mention:
        relevance += 0.20
    relevance += min(0.20, trigger_hits * 0.05)
    if len(snippet.strip()) >= 120:
        relevance += 0.05
    relevance = round(min(1.0, relevance), 2)

    # 3. Recency / Temporal Bonus
    recency_score = 0.88 if published_date else 0.72

    # Weighted Composite Score: 45% Credibility + 40% Relevance + 15% Recency
    composite = round(
        min(1.0, (credibility * 0.45) + (relevance * 0.40) + (recency_score * 0.15)),
        2,
    )

    return EvaluatedSource(
        title=title.strip() or f"{clean_target} Source",
        url=url.strip(),
        snippet=snippet.strip()[:500] or f"Verified source from {source_host}.",
        source_type=source_type,
        published_date=published_date,
        credibility_score=round(credibility, 2),
        relevance_score=relevance,
        composite_score=composite,
    )


def deduplicate_and_rank_sources(
    sources: list[EvaluatedSource],
    min_score: float = 0.0,
    max_results: int = 10,
) -> list[EvaluatedSource]:
    """Deduplicate sources by normalized URL, filter by minimum quality score, and sort best-first."""
    by_url: dict[str, EvaluatedSource] = {}
    for src in sources:
        norm_url = src.url.rstrip("/")
        if src.composite_score < min_score:
            continue
        existing = by_url.get(norm_url)
        if existing is None or src.composite_score > existing.composite_score:
            by_url[norm_url] = src

    ranked = sorted(
        by_url.values(),
        key=lambda s: (s.composite_score, s.credibility_score, s.relevance_score),
        reverse=True,
    )
    return ranked[:max_results]


async def fetch_js_reader_fallback(
    url: str,
    client: httpx.AsyncClient,
    max_chars: int = DEFAULT_SETTINGS.max_scrape_chars,
) -> str:
    """Use Jina Reader headless rendering proxy when static HTML is an empty JS shell."""
    reader_url = f"https://r.jina.ai/{url}"
    try:
        resp = await client.get(
            reader_url,
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
            timeout=10.0,
        )
        if resp.status_code == 200 and len(resp.text.strip()) > 200:
            return " ".join(resp.text.split())[:max_chars]
    except httpx.HTTPError:
        pass
    return ""


async def fetch_external_google_news_rss(
    company_query: str,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    """Query Google News RSS for recent external news coverage and press releases."""
    encoded = quote_plus(f"{company_query} when:180d")
    rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = await client.get(rss_url, timeout=8.0)
        if resp.status_code == 200 and "<rss" in resp.text[:400].lower():
            return parse_rss_or_atom_xml(resp.text, default_source_type="external_news")[:4]
    except httpx.HTTPError:
        pass
    return []


def serialize_evaluated_sources(sources: list[EvaluatedSource]) -> list[dict[str, object]]:
    """Convert a list of EvaluatedSource instances to JSON-serializable dicts."""
    return [asdict(s) for s in sources]
