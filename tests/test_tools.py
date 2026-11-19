"""Unit tests for web scraping and tech-stack HTML parsing tools."""

from __future__ import annotations

from lead_agent.tools.research_engine import (
    deduplicate_and_rank_sources,
    evaluate_source_quality,
    extract_json_ld_and_hydration_state,
    parse_rss_or_atom_xml,
)
from lead_agent.tools.tech_parser import (
    parse_job_board_signals,
    parse_tech_signals_from_html,
)
from lead_agent.tools.web_scraper import (
    extract_clean_page_data,
    normalize_target_url,
)

SAMPLE_COMPANY_HTML = """
<!DOCTYPE html>
<html>
  <head>
    <title>AcmeCloud — Real-Time Data Streaming</title>
    <meta name="description" content="Enterprise Kafka and Snowflake streaming platform." />
    <meta name="generator" content="Astro v4.0" />
    <script src="https://js.stripe.com/v3/"></script>
    <script src="/_next/static/chunks/main.js"></script>
    <script src="https://cdn.segment.com/analytics.js"></script>
  </head>
  <body>
    <header><nav>Navigation menu</nav></header>
    <main>
      <h1>Scale Your Data Pipelines</h1>
      <h2>Q3 Product Release: Zero-Copy Snowflake Connector</h2>
      <p>AcmeCloud processes 5M events/sec on Kubernetes and AWS.</p>
      <a href="/news/q3-release">Read our Press Release</a>
      <a href="https://acmecloud.io/blog/architecture">Engineering Blog</a>
    </main>
    <footer>Footer text</footer>
  </body>
</html>
"""

SAMPLE_CAREERS_HTML = """
<!DOCTYPE html>
<html>
  <head><title>Careers at AcmeCloud</title></head>
  <body>
    <h1>Join Our Engineering Team</h1>
    <h2>Staff Distributed Systems Engineer (Go / Kafka)</h2>
    <p>Requirements: 5+ years with Python, TypeScript, Go, Kubernetes, Terraform, AWS, and Snowflake.</p>
    <h3>Senior AI Platform Engineer (PyTorch / OpenAI / LLM)</h3>
  </body>
</html>
"""


def test_normalize_target_url() -> None:
    assert normalize_target_url("stripe.com") == "https://stripe.com"
    assert normalize_target_url("https://vercel.com") == "https://vercel.com"


def test_extract_clean_page_data_parses_headings_meta_and_news_links() -> None:
    data = extract_clean_page_data(SAMPLE_COMPANY_HTML, "https://acmecloud.io")
    assert data["title"] == "AcmeCloud — Real-Time Data Streaming"
    assert data["meta_description"] == "Enterprise Kafka and Snowflake streaming platform."
    headings = data["headings"]
    assert isinstance(headings, list)
    assert "Scale Your Data Pipelines" in headings
    news_links = data["discovered_news_links"]
    assert isinstance(news_links, list)
    assert len(news_links) == 2
    assert news_links[0]["url"] == "https://acmecloud.io/news/q3-release"


def test_parse_tech_signals_from_html_and_headers() -> None:
    headers = {"server": "cloudflare", "x-vercel-id": "fra1::12345"}
    detected = parse_tech_signals_from_html(SAMPLE_COMPANY_HTML, headers=headers)
    assert "Next.js" in detected
    assert "Stripe" in detected
    assert "Segment" in detected
    assert "Cloudflare" in detected
    assert "Vercel" in detected
    assert "Astro v4.0" in detected


def test_parse_job_board_signals_extracts_roles_and_skills() -> None:
    signals = parse_job_board_signals(SAMPLE_CAREERS_HTML, "https://acmecloud.io/careers")
    skills = signals["detected_job_skills"]
    roles = signals["open_role_signals"]
    assert isinstance(skills, list)
    assert isinstance(roles, list)
    for expected_skill in ("Python", "TypeScript", "Go", "Kafka", "Kubernetes", "Terraform", "AWS", "Snowflake", "OpenAI"):
        assert expected_skill in skills
    assert any("Staff Distributed Systems Engineer" in r for r in roles)
    assert any("Senior AI Platform Engineer" in r for r in roles)


def test_js_heavy_page_recovers_json_ld_and_nextjs_hydration_state() -> None:
    js_spa_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Acme SPA</title>
        <link rel="alternate" type="application/rss+xml" href="/blog/rss.xml" />
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Acme Launches Autonomous Cloud Mesh for Enterprise AI",
            "description": "Acme announces a 40% latency reduction across multi-region Kubernetes clusters.",
            "datePublished": "2026-10-15T08:00:00Z"
          }
        </script>
      </head>
      <body>
        <div id="__next"></div>
        <script id="__NEXT_DATA__" type="application/json">
          {
            "props": {
              "pageProps": {
                "hero": {
                  "headline": "Next-Gen Enterprise Cloud Mesh Architecture",
                  "summary": "Zero-trust service mesh engineered for high-throughput financial workloads."
                }
              }
            }
          }
        </script>
      </body>
    </html>
    """
    state = extract_json_ld_and_hydration_state(js_spa_html)
    assert len(state["json_ld_items"]) == 1  # type: ignore[arg-type]
    assert state["published_dates"] == ["2026-10-15"]

    page_data = extract_clean_page_data(js_spa_html, "https://acme.io")
    assert page_data["published_date"] == "2026-10-15"
    assert page_data["discovered_rss_feeds"] == ["https://acme.io/blog/rss.xml"]
    assert "Acme Launches Autonomous Cloud Mesh for Enterprise AI" in page_data["headings"]  # type: ignore[operator]
    assert "Zero-trust service mesh" in str(page_data["body_excerpt"])


def test_parse_rss_xml_and_evaluate_source_quality() -> None:
    rss_xml = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
      <channel>
        <title>Acme Newsroom</title>
        <item>
          <title>Acme Announces Series C Funding and Enterprise AI Platform Launch</title>
          <link>https://acme.io/news/series-c-launch</link>
          <description>Acme raised $80M to expand its cloud data platform across Europe and North America.</description>
          <pubDate>Wed, 14 Oct 2026 09:30:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    items = parse_rss_or_atom_xml(rss_xml)
    assert len(items) == 1
    assert items[0]["published_date"] == "2026-10-14"

    official_src = evaluate_source_quality(
        title=items[0]["title"],
        url=items[0]["url"],
        snippet=items[0]["snippet"],
        target_domain="acme.io",
        source_type="official_newsroom",
        published_date=items[0]["published_date"],
    )
    generic_src = evaluate_source_quality(
        title="Random Directory Listing",
        url="http://unknown-directory.org/list",
        snippet="Short note.",
        target_domain="acme.io",
        source_type="external_news",
    )

    assert official_src.credibility_score > generic_src.credibility_score
    assert official_src.relevance_score > generic_src.relevance_score
    assert official_src.composite_score >= 0.90

    ranked = deduplicate_and_rank_sources([generic_src, official_src], min_score=0.60)
    assert len(ranked) == 1
    assert ranked[0].url == "https://acme.io/news/series-c-launch"


