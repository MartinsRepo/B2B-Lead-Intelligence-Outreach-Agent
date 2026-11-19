"""Unit tests for Fail-Closed SSRF protection, IP-pinned connections, and DNS Rebinding defense."""

from __future__ import annotations

import socket

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


def test_fail_closed_dns_policy_blocks_unresolvable_domains_by_default() -> None:
    def failing_dns_resolver(host: str) -> list[str]:
        raise socket.gaierror(f"NXDOMAIN for {host}")

    def empty_dns_resolver(_host: str) -> list[str]:
        return []

    # Default strict_dns_failure=True must fail closed when DNS fails or returns no IPs
    res_exception = validate_url_ssrf(
        "https://nonexistent.invalid.example/news",
        dns_resolver=failing_dns_resolver,
    )
    assert res_exception.is_safe is False
    assert "Fail-Closed" in res_exception.reason

    res_empty = validate_url_ssrf(
        "https://empty.invalid.example/news",
        dns_resolver=empty_dns_resolver,
    )
    assert res_empty.is_safe is False
    assert "no IP addresses" in res_empty.reason


def test_dns_resolution_blocks_domain_resolving_to_private_or_metadata_ip() -> None:
    def fake_rebind_resolver(host: str) -> list[str]:
        if host == "rebind.example.com":
            return ["93.184.216.34", "169.254.169.254"]
        if host == "internal-shadow.example.org":
            return ["10.0.0.8"]
        return ["93.184.216.34"]

    outcome = validate_url_ssrf(
        "https://rebind.example.com/news",
        dns_resolver=fake_rebind_resolver,
    )
    assert outcome.is_safe is False
    assert "169.254.169.254" in outcome.reason

    guardrail_outcome = validate_lead_input(
        "rebind.example.com",
        dns_resolver=fake_rebind_resolver,
    )
    assert guardrail_outcome.is_valid is False
    assert "169.254.169.254" in guardrail_outcome.reason


async def test_simulated_toctou_dns_rebinding_prevented_by_ip_pinning() -> None:
    """Simulate a TTL=0 DNS Rebinding attack between validation time and connection time.

    Lookup #1 returns public IP '93.184.216.34'.
    If a second DNS lookup were performed by HTTPX at connect time, Lookup #2 would return
    AWS cloud metadata IP '169.254.169.254'.
    Verify that `safe_http_get` pins '93.184.216.34' directly into the transport request while
    preserving `Host: toctou.example.com` and `extensions['sni_hostname'] = 'toctou.example.com'`.
    """
    lookup_calls: list[str] = []

    def stateful_rebinding_dns(host: str) -> list[str]:
        lookup_calls.append(host)
        if len(lookup_calls) == 1:
            return ["93.184.216.34"]
        # Second lookup flips to private metadata IP!
        return ["169.254.169.254"]

    wire_snapshots: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Capture the exact URL, Host header, and TLS SNI extension at transport send time
        wire_snapshots.append(
            {
                "host": request.url.host,
                "port": request.url.port,
                "path": request.url.path,
                "query": request.url.query,
                "headers": dict(request.headers),
                "extensions": dict(request.extensions),
            }
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text="<html><body>Pinned Public Server Response</body></html>",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await safe_http_get(
            "https://toctou.example.com:8443/press?page=1",
            client,
            dns_resolver=stateful_rebinding_dns,
        )

    # 1. DNS was resolved exactly once (no second TOCTOU lookup)
    assert len(lookup_calls) == 1
    assert len(wire_snapshots) == 1
    sent = wire_snapshots[0]

    # 2. The actual network request connected to the pinned public IP (not the hostname or 169.254.169.254)
    assert sent["host"] == "93.184.216.34"
    assert sent["port"] == 8443
    assert sent["path"] == "/press"
    assert sent["query"] == b"page=1"

    # 3. Host header and TLS SNI hostname remain bound to the original domain name
    sent_headers = sent["headers"]
    sent_ext = sent["extensions"]
    assert isinstance(sent_headers, dict)
    assert isinstance(sent_ext, dict)
    assert sent_headers.get("host") == "toctou.example.com:8443"
    assert sent_ext.get("sni_hostname") == "toctou.example.com"
    assert sent_ext.get("pinned_ip") == "93.184.216.34"

    # 4. Canonical logical URL is restored on the returned response object
    assert str(resp.url) == "https://toctou.example.com:8443/press?page=1"


async def test_same_domain_redirect_dns_rebinding_blocked_on_second_hop() -> None:
    """Simulate a redirect-triggered DNS Rebinding attack on the same domain.

    Hop 1 (`https://hop-rebind.example.com/step1`) resolves to public IP `93.184.216.34` and
    returns `302 Location: /step2`.
    Before Hop 2, the attacker flips the DNS record for `hop-rebind.example.com` to `127.0.0.1`.
    Verify that `safe_http_get` re-validates DNS on Hop 2 and blocks the redirect!
    """
    hop_count = 0

    def rebind_on_second_hop_dns(_host: str) -> list[str]:
        nonlocal hop_count
        hop_count += 1
        if hop_count == 1:
            return ["93.184.216.34"]
        return ["127.0.0.1"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/step1":
            return httpx.Response(302, headers={"Location": "/step2"})
        return httpx.Response(200, text="Should never reach internal /step2")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SSRFBlockedError, match="127.0.0.1"):
            await safe_http_get(
                "https://hop-rebind.example.com/step1",
                client,
                dns_resolver=rebind_on_second_hop_dns,
            )


async def test_safe_http_get_revalidates_redirect_targets_and_blocks_ssrf_redirects() -> None:
    def fake_public_or_rebind_dns(host: str) -> list[str]:
        if host == "evil-redirect-target.example.com":
            return ["192.168.10.25"]
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        # With IP pinning active, request.url.host is '93.184.216.34' and Host header is 'public.example.com'
        assert request.url.host == "93.184.216.34"
        assert request.headers["Host"] == "public.example.com"
        assert request.extensions.get("sni_hostname") == "public.example.com"

        if request.url.path == "/press":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        if request.url.path == "/dns-rebind-redirect":
            return httpx.Response(
                301,
                headers={"Location": "https://evil-redirect-target.example.com/admin"},
            )
        if request.url.path == "/old-news":
            return httpx.Response(
                302,
                headers={"Location": "/newsroom"},
            )
        if request.url.path == "/newsroom":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<html><body>Public Newsroom</body></html>",
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SSRFBlockedError, match="169.254.169.254"):
            await safe_http_get(
                "https://public.example.com/press",
                client,
                dns_resolver=fake_public_or_rebind_dns,
            )

        with pytest.raises(SSRFBlockedError, match="192.168.10.25"):
            await safe_http_get(
                "https://public.example.com/dns-rebind-redirect",
                client,
                dns_resolver=fake_public_or_rebind_dns,
            )

        ok_resp = await safe_http_get(
            "https://public.example.com/old-news",
            client,
            dns_resolver=fake_public_or_rebind_dns,
        )
        assert ok_resp.status_code == 200
        assert str(ok_resp.url) == "https://public.example.com/newsroom"
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
