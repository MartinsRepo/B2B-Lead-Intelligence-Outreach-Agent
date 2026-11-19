"""Multi-source B2B research engine with JS state extraction and dual source/statement scoring."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from lead_agent.config import DEFAULT_SETTINGS
from lead_agent.security import SSRFBlockedError, safe_http_get, validate_url_ssrf

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

QUANTITATIVE_FACT_REGEX = re.compile(
    r"(\b\d+(?:\.\d+)?%|\$\d+|\b\d+\s*(?:million|billion|m|b|k|ms|sec|events/sec|tb|gb|users|customers)\b|\bq[1-4]\s*202\d\b)",
    re.IGNORECASE,
)


@dataclass
class EvaluatedSource:
    """A discovered research source enriched with separate source quality and statement quality scores."""

    title: str
    url: str
    snippet: str
    source_type: str  # "official_newsroom" | "press_release" | "external_news" | "rss_feed" | "corporate_website"
    published_date: str = ""
    updated_date: str = ""
    age_days: int | None = None
    recency_score: float = 0.55
    credibility_score: float = 0.80
    source_quality_score: float = 0.80
    statement_quality_score: float = 0.80
    relevance_score: float = 0.80
    composite_score: float = 0.80


def extract_json_ld_and_hydration_state(html: str) -> dict[str, object]:
    """Extract structured data from JSON-LD (<script type='application/ld+json'>) and Next.js/__NEXT_DATA__.

    Separately extracts publication dates (`published_dates`) and modification dates (`updated_dates`).
    """
    soup = BeautifulSoup(html, "html.parser")
    json_ld_items: list[dict[str, str]] = []
    hydration_snippets: list[str] = []
    published_dates: list[str] = []
    updated_dates: list[str] = []

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
                    date_pub = _normalize_date_string(
                        str(item.get("datePublished") or item.get("dateCreated") or "").strip()
                    )
                    date_mod = _normalize_date_string(
                        str(item.get("dateModified") or "").strip()
                    )
                    if date_pub and date_pub not in published_dates:
                        published_dates.append(date_pub)
                    if date_mod and date_mod not in updated_dates:
                        updated_dates.append(date_mod)
                    if headline or desc:
                        json_ld_items.append(
                            {
                                "type": str(item.get("@type", "Thing")),
                                "headline": headline,
                                "description": desc[:600],
                                "date": date_pub or date_mod,
                                "published_date": date_pub,
                                "updated_date": date_mod,
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

    # 3. Check OpenGraph / article published time vs. modified/updated time meta tags
    pub_meta = soup.find(
        "meta",
        attrs={"property": re.compile(r"^article:published_time$", re.I)},
    ) or soup.find("meta", attrs={"name": re.compile(r"^(date|pubdate|publish-date)$", re.I)})
    if pub_meta and pub_meta.get("content"):
        p_str = _normalize_date_string(str(pub_meta["content"]).strip())
        if p_str and p_str not in published_dates:
            published_dates.append(p_str)

    upd_meta = soup.find(
        "meta",
        attrs={"property": re.compile(r"^(article:modified_time|og:updated_time)$", re.I)},
    ) or soup.find("meta", attrs={"name": re.compile(r"^(lastmod|last-modified|updated)$", re.I)})
    if upd_meta and upd_meta.get("content"):
        u_str = _normalize_date_string(str(upd_meta["content"]).strip())
        if u_str and u_str not in updated_dates:
            updated_dates.append(u_str)

    return {
        "json_ld_items": json_ld_items[:10],
        "hydration_snippets": hydration_snippets[:12],
        "published_dates": published_dates[:5],
        "updated_dates": updated_dates[:5],
    }


def _collect_informative_strings(
    node: object, acc: list[str], max_items: int = 20
) -> None:
    """Recursively collect human-readable sentences from a hydration JSON tree."""
    if len(acc) >= max_items:
        return
    if isinstance(node, str):
        cleaned = " ".join(node.split())
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
    """Discover SSRF-validated RSS or Atom feed links embedded in a webpage's HTML."""
    soup = BeautifulSoup(html, "html.parser")
    feeds: list[str] = []
    for link in soup.find_all("link", href=True):
        link_type = str(link.get("type", "")).lower()
        href = str(link["href"]).strip()
        if (
            "rss" in link_type
            or "atom" in link_type
            or "xml" in link_type
            or href.endswith((".rss", "/feed", "/feed/", "/rss.xml", "/atom.xml"))
        ):
            full = urljoin(base_url, href)
            if full not in feeds and validate_url_ssrf(full, resolve_dns=False).is_safe:
                feeds.append(full)
    return feeds[:4]


def parse_rss_or_atom_xml(
    xml_text: str, default_source_type: str = "rss_feed"
) -> list[dict[str, str]]:
    """Parse standard RSS 2.0 or Atom XML feeds, separating published_date and updated_date."""
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return items

    channel_updated = _normalize_date_string(
        (root.findtext(".//lastBuildDate") or "").strip()
    )

    # RSS 2.0 <item> elements
    for item in root.findall(".//item")[:8]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc_raw = (item.findtext("description") or "").strip()
        pub_date = _normalize_date_string((item.findtext("pubDate") or "").strip())
        upd_date = ""
        for child in item:
            tag_name = child.tag.split("}")[-1].lower()
            if tag_name in {"updated", "modified", "lastbuilddate"} and child.text:
                upd_date = _normalize_date_string(child.text.strip())
        if not upd_date and channel_updated and channel_updated != pub_date:
            upd_date = channel_updated

        clean_desc = " ".join(BeautifulSoup(desc_raw, "html.parser").get_text(" ", strip=True).split())
        if title and validate_url_ssrf(link, resolve_dns=False).is_safe:
            items.append(
                {
                    "title": title,
                    "url": link,
                    "snippet": (clean_desc or title)[:500],
                    "published_date": pub_date,
                    "updated_date": upd_date,
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
            upd_date = ""
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
                elif tag_name == "published" and child.text:
                    pub_date = _normalize_date_string(child.text.strip())
                elif tag_name in {"updated", "modified"} and child.text:
                    upd_date = _normalize_date_string(child.text.strip())
            if title and validate_url_ssrf(link, resolve_dns=False).is_safe:
                items.append(
                    {
                        "title": title,
                        "url": link,
                        "snippet": (summary or title)[:500],
                        "published_date": pub_date,
                        "updated_date": upd_date,
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
        return ""


def parse_iso_date(date_str: str) -> date | None:
    """Parse a normalized YYYY-MM-DD (or RFC-2822) string into a `datetime.date`."""
    norm = _normalize_date_string(date_str)
    if not norm or not re.match(r"^\d{4}-\d{2}-\d{2}$", norm):
        return None
    try:
        return date.fromisoformat(norm)
    except ValueError:
        return None


def _decay_score_for_age_days(age_days: int) -> float:
    """Compute time-decay recency score (0.25 to 0.98) from the age of a news item in days."""
    if age_days <= 30:
        return 0.98
    if age_days <= 90:
        return 0.90
    if age_days <= 180:
        return 0.80
    if age_days <= 365:
        return 0.65
    if age_days <= 730:
        return 0.45
    return 0.25


def compute_recency_score(
    published_date: str = "",
    updated_date: str = "",
    reference_date: date | None = None,
) -> tuple[float, int | None]:
    """Calculate recency score and actual age in days, distinguishing publication vs. update dates.

    - If both `published_date` and `updated_date` exist: `age_days` reflects the true publication age,
      while `recency_score` blends 70% publication freshness + 30% update freshness.
    - If only `published_date` exists: uses publication age directly.
    - If only `updated_date` exists: discounts slightly (x0.90) compared to an explicit publication date.
    - If neither exists: returns neutral static-page recency (`0.55`, `None`).
    """
    ref = reference_date or datetime.now(UTC).date()
    pub_dt = parse_iso_date(published_date)
    upd_dt = parse_iso_date(updated_date)

    if pub_dt is not None and upd_dt is not None:
        pub_age = max(0, (ref - pub_dt).days)
        upd_age = max(0, (ref - upd_dt).days)
        blended = (_decay_score_for_age_days(pub_age) * 0.70) + (
            _decay_score_for_age_days(upd_age) * 0.30
        )
        return round(blended, 2), pub_age

    if pub_dt is not None:
        pub_age = max(0, (ref - pub_dt).days)
        return _decay_score_for_age_days(pub_age), pub_age

    if upd_dt is not None:
        upd_age = max(0, (ref - upd_dt).days)
        return round(_decay_score_for_age_days(upd_age) * 0.90, 2), upd_age

    return 0.55, None


def evaluate_statement_quality(
    title: str,
    snippet: str,
    company_token: str,
    clean_target: str,
    source_host: str,
) -> float:
    """Evaluate Aussagequalität (statement quality: trigger density, factual specificity, entity relevance)."""
    combined_text = f"{title} {snippet}"
    lower_text = combined_text.lower()

    trigger_hits = sum(
        1 for kw in B2B_TRIGGER_KEYWORDS if re.search(rf"\b{kw}\b", lower_text)
    )
    has_company_mention = bool(company_token and company_token in lower_text) or (
        bool(clean_target) and clean_target in source_host
    )
    quant_matches = QUANTITATIVE_FACT_REGEX.findall(combined_text)

    score = 0.45
    if has_company_mention:
        score += 0.20
    score += min(0.20, trigger_hits * 0.05)
    if quant_matches:
        score += min(0.10, len(quant_matches) * 0.05)
    if len(snippet.strip()) >= 80:
        score += 0.05

    return round(min(1.0, score), 2)


def evaluate_source_quality(
    title: str,
    url: str,
    snippet: str,
    target_domain: str,
    source_type: str = "corporate_website",
    published_date: str = "",
    updated_date: str = "",
    reference_date: date | None = None,
) -> EvaluatedSource:
    """Compute separate Source Quality (Quellenqualität) and Statement Quality (Aussagequalität) scores."""
    parsed_url = urlparse(url)
    source_host = (parsed_url.hostname or "").lower().removeprefix("www.")
    clean_target = (
        urlparse(target_domain if "://" in target_domain else f"https://{target_domain}").hostname
        or target_domain
    ).lower().removeprefix("www.")
    company_token = clean_target.split(".")[0]

    # 1. Domain Provenance & Credibility Score
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

    # 2. Actual Age & Recency Score (distinguishing published_date vs. updated_date)
    norm_pub = _normalize_date_string(published_date)
    norm_upd = _normalize_date_string(updated_date)
    recency_score, age_days = compute_recency_score(
        published_date=norm_pub,
        updated_date=norm_upd,
        reference_date=reference_date,
    )

    # 3. Source Quality Score (Quellenqualität: 72% Provenance/Credibility + 28% Age/Recency)
    source_quality = round(min(1.0, (credibility * 0.72) + (recency_score * 0.28)), 2)

    # 4. Statement Quality Score (Aussagequalität: Entity Relevance + B2B Triggers + Quantitative Facts)
    statement_quality = evaluate_statement_quality(
        title=title,
        snippet=snippet,
        company_token=company_token,
        clean_target=clean_target,
        source_host=source_host,
    )

    # 5. Overall Composite Score (55% Source Quality + 45% Statement Quality)
    composite = round(
        min(1.0, (source_quality * 0.55) + (statement_quality * 0.45)),
        2,
    )

    return EvaluatedSource(
        title=title.strip() or f"{clean_target} Source",
        url=url.strip(),
        snippet=snippet.strip()[:500] or f"Verified source from {source_host}.",
        source_type=source_type,
        published_date=norm_pub,
        updated_date=norm_upd,
        age_days=age_days,
        recency_score=recency_score,
        credibility_score=round(credibility, 2),
        source_quality_score=source_quality,
        statement_quality_score=statement_quality,
        relevance_score=statement_quality,
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
        key=lambda s: (
            s.composite_score,
            s.source_quality_score,
            s.statement_quality_score,
        ),
        reverse=True,
    )
    return ranked[:max_results]


async def fetch_js_reader_fallback(
    url: str,
    client: httpx.AsyncClient,
    max_chars: int = DEFAULT_SETTINGS.max_scrape_chars,
) -> str:
    """Use Jina Reader headless rendering proxy when static HTML is an empty JS shell."""
    if not validate_url_ssrf(url).is_safe:
        return ""
    reader_url = f"https://r.jina.ai/{url}"
    try:
        resp = await safe_http_get(
            reader_url,
            client,
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
            timeout=10.0,
        )
        if resp.status_code == 200 and len(resp.text.strip()) > 200:
            return " ".join(resp.text.split())[:max_chars]
    except (httpx.HTTPError, SSRFBlockedError):
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
        resp = await safe_http_get(rss_url, client, timeout=8.0)
        if resp.status_code == 200 and "<rss" in resp.text[:400].lower():
            return parse_rss_or_atom_xml(resp.text, default_source_type="external_news")[:4]
    except (httpx.HTTPError, SSRFBlockedError):
        pass
    return []


def serialize_evaluated_sources(sources: list[EvaluatedSource]) -> list[dict[str, object]]:
    """Convert a list of EvaluatedSource instances to JSON-serializable dicts."""
    return [asdict(s) for s in sources]
