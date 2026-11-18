"""Unit tests for web scraping and tech-stack HTML parsing tools."""

from __future__ import annotations

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

