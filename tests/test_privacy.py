"""Unit tests for GDPR / DSGVO compliance (PII filtering, data minimization, retention TTL, Art. 21 opt-out, Art. 14 transparency)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from lead_agent.config import AgentSettings
from lead_agent.guardrails import validate_lead_input
from lead_agent.privacy import (
    OptOutBlocklistManager,
    compute_retention_timestamps,
    get_art14_outreach_footer,
    is_personal_profile_url,
    is_timestamp_expired,
    minimize_corporate_text,
    scrub_personal_data,
    strip_personal_dom_elements,
)
from lead_agent.tools.research_engine import extract_json_ld_and_hydration_state
from lead_agent.tools.tech_parser import parse_job_board_signals
from lead_agent.tools.web_scraper import (
    extract_clean_page_data,
    fetch_company_news_and_press_impl,
    scrape_company_website_impl,
)


def test_scrub_personal_data_redacts_emails_phones_profiles_and_contact_names() -> None:
    """Requirement 1: Filter out personal data (PII) from websites while keeping corporate dates & metrics intact."""
    raw_text = (
        "Published on 2026-10-15: Acme Cloud processes 5M events/sec. "
        "Press Contact: Frau Dr. Julia Schmidt (julia.schmidt@acme.example, Tel: +49 (0) 89 12345-67). "
        "Recruiter: Mr. John Smith, https://www.linkedin.com/in/john-smith-98765/ "
        "or contact Herr Thomas Müller at +1-555-234-5678."
    )
    cleaned = scrub_personal_data(raw_text)

    # PII must be scrubbed
    assert "julia.schmidt@acme.example" not in cleaned
    assert "[REDACTED_EMAIL]" in cleaned
    assert "+49 (0) 89 12345-67" not in cleaned
    assert "+1-555-234-5678" not in cleaned
    assert "[REDACTED_PHONE]" in cleaned
    assert "linkedin.com/in/john-smith-98765" not in cleaned
    assert "[REDACTED_PERSONAL_PROFILE]" in cleaned
    assert "Julia Schmidt" not in cleaned
    assert "John Smith" not in cleaned
    assert "Thomas Müller" not in cleaned

    # Corporate dates and metrics must NOT be corrupted
    assert "2026-10-15" in cleaned
    assert "5M events/sec" in cleaned


def test_strip_personal_dom_elements_and_json_ld_person_filtering() -> None:
    """Requirement 1 & 2: DOM elements (<author>, <address>, .recruiter, .team-member) and JSON-LD Person schemas are stripped."""
    html = """
    <html>
      <head>
        <title>Acme Enterprise Cloud Platform</title>
        <meta name="author" content="Max Mustermann" />
        <meta name="description" content="Acme scales Kubernetes infrastructure. Contact press@acme.example." />
        <script type="application/ld+json">
          [
            {"@type": "Person", "name": "Jane Doe", "email": "jane.doe@acme.example"},
            {"@type": "NewsArticle", "headline": "Acme Launches Multi-Region Kubernetes Mesh", "datePublished": "2026-10-12"}
          ]
        </script>
      </head>
      <body>
        <h1>Acme Enterprise Cloud</h1>
        <div class="byline">Written by Max Mustermann</div>
        <div class="recruiter">Your Recruiter: Frau Anna Weber (anna.weber@acme.example)</div>
        <address>Direct Phone: +49 89 55566677</address>
        <p>Acme provides enterprise observability and multi-region cloud orchestration.</p>
      </body>
    </html>
    """
    page_data = extract_clean_page_data(html, "https://acme.example")
    ld_data = extract_json_ld_and_hydration_state(html)

    assert "Max Mustermann" not in page_data["body_excerpt"]
    assert "Anna Weber" not in page_data["body_excerpt"]
    assert "anna.weber@acme.example" not in page_data["body_excerpt"]
    assert "press@acme.example" not in page_data["meta_description"]
    assert "[REDACTED_EMAIL]" in page_data["meta_description"]

    # JSON-LD Person must be ignored, while NewsArticle is preserved
    json_ld_items = ld_data["json_ld_items"]
    assert isinstance(json_ld_items, list)
    headlines = [a["headline"] for a in json_ld_items]
    assert "Acme Launches Multi-Region Kubernetes Mesh" in headlines
    assert all("Jane Doe" not in a["headline"] and "Jane Doe" not in a["description"] for a in json_ld_items)

    soup = BeautifulSoup(html, "html.parser")
    strip_personal_dom_elements(soup)
    assert soup.find("address") is None
    assert soup.select(".recruiter") == []


def test_data_minimization_on_careers_and_company_pages() -> None:
    """Requirement 2: Enforce data minimization on careers and corporate pages (truncate & strip recruiter PII)."""
    careers_html = """
    <html>
      <body>
        <h2>Senior Platform Engineer - Kubernetes</h2>
        <div class="contact-person">Ansprechpartnerin: Frau Sarah Klein, sarah.klein@acme.example, Tel: +49 30 99887766</div>
        <p>We are scaling our AWS, Terraform, and Kafka infrastructure across Europe. Apply directly to jobs@acme.example.</p>
      </body>
    </html>
    """
    parsed = parse_job_board_signals(careers_html, page_url="https://acme.example/careers", max_excerpt_chars=120)
    assert "Senior Platform Engineer - Kubernetes" in parsed["open_role_signals"]
    assert "Kubernetes" in parsed["detected_job_skills"]
    assert "sarah.klein@acme.example" not in parsed["excerpt"]
    assert "jobs@acme.example" not in parsed["excerpt"]
    assert "Sarah Klein" not in parsed["excerpt"]
    assert len(parsed["excerpt"]) <= 120

    minimized = minimize_corporate_text("Contact ceo@acme.example   " * 50, max_chars=80, redact_pii=True)
    assert len(minimized) <= 80
    assert "ceo@acme.example" not in minimized


def test_retention_timestamps_and_automated_expiration_check() -> None:
    """Requirement 3: Implement deletion and retention periods (TTL calculation and expiration verification)."""
    base_time = datetime(2026, 11, 20, 10, 0, 0, tzinfo=UTC)
    created_utc, expires_utc = compute_retention_timestamps(ttl_seconds=1800, now_utc=base_time)

    assert created_utc == "2026-11-20T10:00:00Z"
    assert expires_utc == "2026-11-20T10:30:00Z"

    # 15 minutes later -> not expired
    assert not is_timestamp_expired(expires_utc, now_utc=base_time + timedelta(minutes=15))
    # 30 minutes later -> expired
    assert is_timestamp_expired(expires_utc, now_utc=base_time + timedelta(minutes=30))
    # 45 minutes later -> expired
    assert is_timestamp_expired(expires_utc, now_utc=base_time + timedelta(minutes=45))


@pytest.mark.asyncio
async def test_art21_opt_out_blocklist_blocks_domain_and_subdomains(tmp_path: Path) -> None:
    """Requirement 4: Art. 21 GDPR objection and domain blocklist mechanism across guardrail, persistence, and scraper."""
    storage_file = tmp_path / "opt_out_domains.json"
    manager = OptOutBlocklistManager(initial_domains=["opted-out-corp.com"], storage_path=storage_file)
    manager.add_domain("https://www.no-outreach.de/imprint")

    assert "opted-out-corp.com" in manager.blocked_domains
    assert "no-outreach.de" in manager.blocked_domains

    # Reload from persisted JSON file
    reloaded = OptOutBlocklistManager(storage_path=storage_file)
    is_blocked, reason = reloaded.is_opted_out("https://careers.no-outreach.de/jobs")
    assert is_blocked
    assert "Art. 21 GDPR" in reason

    # Input guardrail must reject opted-out domains and their subdomains
    settings = AgentSettings(opt_out_domains=("opted-out-corp.com",))
    outcome = validate_lead_input("https://news.opted-out-corp.com/press", settings=settings)
    assert not outcome.is_valid
    assert "Art. 21 GDPR" in outcome.reason

    # Web scraper and news fetcher must also refuse to fetch an opted-out domain
    with patch("lead_agent.tools.web_scraper.DEFAULT_OPT_OUT_MANAGER", reloaded):
        scraped = await scrape_company_website_impl("https://www.no-outreach.de")
        assert scraped["body_excerpt"] == ""
        assert "Art. 21 GDPR" in str(scraped.get("error", ""))

        news = await fetch_company_news_and_press_impl("https://www.no-outreach.de")
        assert news["articles"] == []
        assert "Art. 21 GDPR" in str(news.get("error", ""))

    # Removing domain restores access
    reloaded.remove_domain("no-outreach.de")
    assert not reloaded.is_opted_out("no-outreach.de")[0]


def test_personal_linkedin_profile_blocked_while_company_profile_allowed() -> None:
    """Requirement 1 & 4: Block personal LinkedIn profiles (/in/, /pub/) while allowing corporate LinkedIn URLs (/company/)."""
    assert is_personal_profile_url("https://www.linkedin.com/in/jane-doe-12345/")
    assert is_personal_profile_url("linkedin.com/pub/john-doe/1/2/3")
    assert not is_personal_profile_url("https://www.linkedin.com/company/openai")

    personal_outcome = validate_lead_input("https://www.linkedin.com/in/jane-doe-12345/")
    assert not personal_outcome.is_valid
    assert "GDPR Data Minimization" in personal_outcome.reason

    company_outcome = validate_lead_input("https://www.linkedin.com/company/openai")
    assert company_outcome.is_valid


def test_art14_transparency_notice_generated() -> None:
    """Requirement 5: Prepare GDPR Art. 13/14 transparency notice and verify docs/privacy_art13_14.md exists."""
    notice = get_art14_outreach_footer("Acme Corp")
    assert "Art. 14 GDPR" in notice
    assert "Art. 21 GDPR" in notice
    assert "Acme Corp" in notice

    privacy_doc = Path(__file__).resolve().parents[1] / "docs" / "privacy_art13_14.md"
    assert privacy_doc.exists()
    content = privacy_doc.read_text(encoding="utf-8")
    assert "Art. 13" in content
    assert "Art. 14" in content
    assert "Art. 21" in content
