"""Unit tests for SSRF protection, DNS resolution checks, redirect validation, and RSS/source filtering."""

from __future__ import annotations

import httpx
import pytest

from lead_agent.guardrails import validate_lead_input, validate_lead_output
from lead_agent.schemas import (
    LeadReport,
    OutreachPitch,
    SourceCitation,
    TechStackAnalysis,
)
from lead_agent.security import (
    SSRFBlockedError,
    is_ip_blocked,
    safe_http_get,
    validate_url_ssrf,
)
from lead_agent.tools.research_engine import (
    discover_rss_feed_urls,
    parse_rss_or_atom_xml,
)
from lead_agent.tools.web_scraper import extract_clean_page_data


@pytest.mark.parametrize(
    "blocked_ip",
    [
        "127.0.0.1",
        "127.0.0.53",
        "10.0.0.1",
        "172.16.0.10",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",  # AWS/GCP/Azure Cloud Metadata IP
        "100.64.0.1",       # RFC 6598 Carrier-Grade NAT
        "198.18.0.1",       # RFC 2544 Benchmark network
        "192.0.2.1",        # TEST-NET-1
        "224.0.0.1",        # Multicast
        "240.0.0.1",        # Reserved
        "0.0.0.0",          # Unspecified
        "::1",              # IPv6 Loopback
        "fc00::1",          # IPv6 Unique Local
        "fe80::1",          # IPv6 Link-Local
        "::ffff:127.0.0.1", # IPv4-mapped IPv6 Loopback
        "::ffff:169.254.169.254",  # IPv4-mapped IPv6 Metadata
    ],
)
def test_is_ip_blocked_blocks_all_private_and_reserved_ranges(blocked_ip: str) -> None:
    blocked, reason = is_ip_blocked(blocked_ip)
    assert blocked is True
    assert reason


@pytest.mark.parametrize(
    "public_ip",
    [
        "93.184.216.34",
        "8.8.8.8",
        "1.1.1.1",
        "2606:2800:220:1:248:1893:25c8:1946",
    ],
)
def test_is_ip_blocked_allows_public_ips(public_ip: str) -> None:
    blocked, _ = is_ip_blocked(public_ip)
    assert blocked is False


def test_dns_resolution_blocks_domain_resolving_to_private_or_metadata_ip() -> None:
    # Simulate DNS rebinding where a public-looking domain resolves to 169.254.169.254 or 10.0.0.8
    def fake_rebind_resolver(host: str) -> list[str]:
        if host == "rebind.example.com":
            return ["93.184.216.34", "169.254.169.254"]
        if host == "internal- shadow.example.org":
            return ["10.0.0.8"]
        return ["93.184.216.34"]

    outcome = validate_url_ssrf(
        "https://rebind.example.com/news",
        dns_resolver=fake_rebind_resolver,
    )
    assert outcome.is_safe is False
    assert "169.254.169.254" in outcome.reason

    # Input Guardrail must also block a domain whose DNS resolves to a private IP
    guardrail_outcome = validate_lead_input(
        "rebind.example.com",
        dns_resolver=fake_rebind_resolver,
    )
    assert guardrail_outcome.is_valid is False
    assert "169.254.169.254" in guardrail_outcome.reason


async def test_safe_http_get_revalidates_redirect_targets_and_blocks_ssrf_redirects() -> None:
    def fake_public_or_rebind_dns(host: str) -> list[str]:
        if host == "evil-redirect-target.example.com":
            return ["192.168.10.25"]
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == "https://public.example.com/press":
            # Redirect to AWS metadata IP
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        if url_str == "https://public.example.com/dns-rebind-redirect":
            # Redirect to a domain that resolves via DNS to a private 192.168.x.x IP
            return httpx.Response(
                301,
                headers={"Location": "https://evil-redirect-target.example.com/admin"},
            )
        if url_str == "https://public.example.com/old-news":
            # Safe redirect to another public page
            return httpx.Response(
                302,
                headers={"Location": "/newsroom"},
            )
        if url_str == "https://public.example.com/newsroom":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<html><body>Public Newsroom</body></html>",
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # 1. Redirect to cloud metadata IP must be blocked before following
        with pytest.raises(SSRFBlockedError, match="169.254.169.254"):
            await safe_http_get(
                "https://public.example.com/press",
                client,
                dns_resolver=fake_public_or_rebind_dns,
            )

        # 2. Redirect to domain resolving to private IP 192.168.10.25 must be blocked
        with pytest.raises(SSRFBlockedError, match="192.168.10.25"):
            await safe_http_get(
                "https://public.example.com/dns-rebind-redirect",
                client,
                dns_resolver=fake_public_or_rebind_dns,
            )

        # 3. Legitimate redirect to public /newsroom succeeds
        ok_resp = await safe_http_get(
            "https://public.example.com/old-news",
            client,
            dns_resolver=fake_public_or_rebind_dns,
        )
        assert ok_resp.status_code == 200
        assert "Public Newsroom" in ok_resp.text


def test_rss_and_external_source_urls_filtered_against_ssrf() -> None:
    html_with_unsafe_links = """
    <html>
      <head>
        <link rel="alternate" type="application/rss+xml" href="https://acme.io/feed.xml" />
        <link rel="alternate" type="application/rss+xml" href="http://169.254.169.254/latest/meta-data" />
        <link rel="alternate" type="application/rss+xml" href="http://internal.corp/rss.xml" />
      </head>
      <body>
        <a href="https://acme.io/press/release-1">Valid Press Release</a>
        <a href="http://127.0.0.1:8080/press/secret">Localhost Press Link</a>
        <a href="http://10.0.0.5/news/internal">Private Network News</a>
      </body>
    </html>
    """
    feeds = discover_rss_feed_urls(html_with_unsafe_links, "https://acme.io")
    assert feeds == ["https://acme.io/feed.xml"]

    page_data = extract_clean_page_data(html_with_unsafe_links, "https://acme.io")
    news_urls = [item["url"] for item in page_data["discovered_news_links"]]  # type: ignore[index]
    assert news_urls == ["https://acme.io/press/release-1"]

    rss_xml_with_ssrf_items = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
      <channel>
        <title>Feed</title>
        <item>
          <title>Public Launch</title>
          <link>https://acme.io/news/public-launch</link>
          <description>Safe article.</description>
        </item>
        <item>
          <title>Internal Metadata Exploit</title>
          <link>http://169.254.169.254/latest/meta-data/iam</link>
          <description>Unsafe SSRF link inside RSS feed.</description>
        </item>
        <item>
          <title>Localhost Admin</title>
          <link>http://localhost:9000/admin</link>
          <description>Unsafe localhost link.</description>
        </item>
      </channel>
    </rss>
    """
    parsed_items = parse_rss_or_atom_xml(rss_xml_with_ssrf_items)
    assert len(parsed_items) == 1
    assert parsed_items[0]["url"] == "https://acme.io/news/public-launch"

    # Output Guardrail must also reject a LeadReport whose SourceCitation points to a private/reserved IP
    unsafe_report = LeadReport(
        company_name="Acme",
        target_domain="https://acme.io",
        industry="SaaS",
        executive_summary="Summary.",
        recent_news_and_triggers=["Trigger."],
        identified_pain_points=["Pain point."],
        tech_stack=TechStackAnalysis(
            detected_technologies=["Python"],
            hiring_signals=["Engineer"],
            inferred_infrastructure_needs="Cloud.",
        ),
        outreach=OutreachPitch(
            subject_line="Subject",
            hyper_personalized_pitch="A valid personalized outreach pitch with sufficient length for validation.",
            icebreaker_hook="Hook",
            call_to_action="CTA",
        ),
        sources=[
            SourceCitation(
                title="Metadata SSRF",
                url="http://169.254.169.254/latest/meta-data",
                snippet="Snippet",
            )
        ],
    )
    out_check = validate_lead_output(unsafe_report)
    assert out_check.is_valid is False
    assert "169.254" in out_check.reason
