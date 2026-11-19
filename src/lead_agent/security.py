"""SSRF protection, Fail-Closed DNS verification, and IP-pinned HTTP client utilities."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }
)

BLOCKED_HOSTNAME_SUFFIXES: tuple[str, ...] = (
    ".local",
    ".internal",
    ".localhost",
    ".localdomain",
    ".home.arpa",
    ".intranet",
    ".corp",
    ".lan",
)

# Explicit special/reserved IPv4 & IPv6 CIDR ranges in addition to ipaddress flags
EXTRA_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918 Private
    ipaddress.ip_network("100.64.0.0/10"),      # RFC 6598 Carrier-Grade NAT (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-Local & Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 Private
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 Private
    ipaddress.ip_network("198.18.0.0/15"),      # Network benchmark / inter-network communications
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for future use / Broadcast
    ipaddress.ip_network("::1/128"),            # IPv6 Loopback
    ipaddress.ip_network("::/128"),             # IPv6 Unspecified
    ipaddress.ip_network("fc00::/7"),           # IPv6 Unique Local (ULA)
    ipaddress.ip_network("fe80::/10"),          # IPv6 Link-Local
    ipaddress.ip_network("ff00::/8"),           # IPv6 Multicast
)


class SSRFBlockedError(ValueError):
    """Raised when a URL, DNS resolution, or HTTP redirect target violates SSRF security rules."""


@dataclass(frozen=True)
class SSRFCheckOutcome:
    """Result of an SSRF URL and Fail-Closed DNS validation check."""

    is_safe: bool
    url: str
    hostname: str
    resolved_ips: tuple[str, ...]
    reason: str


def is_ip_blocked(ip_str: str) -> tuple[bool, str]:
    """Check whether an IPv4 or IPv6 address belongs to any private, loopback, link-local, or reserved range."""
    cleaned = ip_str.strip().strip("[]")
    if "%" in cleaned:
        cleaned = cleaned.split("%", 1)[0]

    try:
        ip_obj = ipaddress.ip_address(cleaned)
    except ValueError:
        return True, f"Malformed IP address '{ip_str}'."

    # Unwrap IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1 or ::ffff:169.254.169.254)
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        ip_obj = ip_obj.ipv4_mapped

    for net in EXTRA_BLOCKED_NETWORKS:
        if ip_obj.version == net.version and ip_obj in net:
            return (
                True,
                f"IP address '{ip_obj}' is in blocked/reserved network {net}.",
            )

    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return (
            True,
            f"IP address '{ip_obj}' is a private, loopback, link-local, or reserved address.",
        )

    return False, f"IP address '{ip_obj}' is a valid public address."


def resolve_hostname_ips(hostname: str) -> list[str]:
    """Resolve all IPv4 and IPv6 addresses for `hostname` via the system DNS resolver."""
    infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and isinstance(sockaddr[0], str):
            ip_val = sockaddr[0]
            if ip_val not in ips:
                ips.append(ip_val)
    return ips


def validate_url_ssrf(
    url: str,
    block_private_ips: bool = True,
    resolve_dns: bool = True,
    dns_resolver: Callable[[str], list[str]] | None = None,
    strict_dns_failure: bool = True,
) -> SSRFCheckOutcome:
    """Validate a URL against SSRF vectors using a Fail-Closed DNS resolution strategy by default."""
    cleaned = url.strip()
    if not cleaned:
        return SSRFCheckOutcome(
            is_safe=False,
            url="",
            hostname="",
            resolved_ips=(),
            reason="URL cannot be empty.",
        )

    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return SSRFCheckOutcome(
            is_safe=False,
            url=cleaned,
            hostname="",
            resolved_ips=(),
            reason=f"Unsupported or unsafe URL scheme '{scheme}'. Only http:// and https:// are permitted.",
        )

    hostname = (parsed.hostname or "").lower().strip(".")
    if not hostname:
        return SSRFCheckOutcome(
            is_safe=False,
            url=cleaned,
            hostname="",
            resolved_ips=(),
            reason=f"URL '{cleaned}' does not contain a valid hostname.",
        )

    if not block_private_ips:
        return SSRFCheckOutcome(
            is_safe=True,
            url=cleaned,
            hostname=hostname,
            resolved_ips=(),
            reason="Private IP blocking disabled by configuration.",
        )

    # 1. Check literal IP address hostnames first (e.g. http://127.0.0.1, http://169.254.169.254, http://[::1])
    raw_host_ip = hostname.strip("[]")
    try:
        ipaddress.ip_address(raw_host_ip)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False

    if is_literal_ip:
        blocked, ip_reason = is_ip_blocked(raw_host_ip)
        if blocked:
            return SSRFCheckOutcome(
                is_safe=False,
                url=cleaned,
                hostname=hostname,
                resolved_ips=(raw_host_ip,),
                reason=f"SSRF Guardrail blocked literal IP host '{hostname}': {ip_reason}",
            )
        return SSRFCheckOutcome(
            is_safe=True,
            url=cleaned,
            hostname=hostname,
            resolved_ips=(raw_host_ip,),
            reason="Literal IP host is public.",
        )

    # 2. Check blocked internal/local hostnames and suffixes
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(BLOCKED_HOSTNAME_SUFFIXES):
        return SSRFCheckOutcome(
            is_safe=False,
            url=cleaned,
            hostname=hostname,
            resolved_ips=(),
            reason=f"Host '{hostname}' is a private/local address and is blocked by the SSRF Guardrail.",
        )

    # 3. Resolve DNS (A/AAAA records) with Fail-Closed enforcement and verify every resolved IP is public
    resolved_ips: list[str] = []
    if resolve_dns:
        resolver_fn = dns_resolver or resolve_hostname_ips
        try:
            resolved_ips = resolver_fn(hostname)
        except Exception as exc:
            if strict_dns_failure:
                return SSRFCheckOutcome(
                    is_safe=False,
                    url=cleaned,
                    hostname=hostname,
                    resolved_ips=(),
                    reason=(
                        f"Fail-Closed SSRF Guardrail blocked host '{hostname}': "
                        f"DNS resolution failed ({exc!s})."
                    ),
                )
            resolved_ips = []

        if strict_dns_failure and not resolved_ips:
            return SSRFCheckOutcome(
                is_safe=False,
                url=cleaned,
                hostname=hostname,
                resolved_ips=(),
                reason=(
                    f"Fail-Closed SSRF Guardrail blocked host '{hostname}': "
                    "DNS lookup returned no IP addresses."
                ),
            )

        for ip_addr in resolved_ips:
            blocked, ip_reason = is_ip_blocked(ip_addr)
            if blocked:
                return SSRFCheckOutcome(
                    is_safe=False,
                    url=cleaned,
                    hostname=hostname,
                    resolved_ips=tuple(resolved_ips),
                    reason=(
                        f"SSRF DNS Guardrail blocked host '{hostname}' because it resolved to "
                        f"non-public IP '{ip_addr}': {ip_reason}"
                    ),
                )

    return SSRFCheckOutcome(
        is_safe=True,
        url=cleaned,
        hostname=hostname,
        resolved_ips=tuple(resolved_ips),
        reason="URL passed all SSRF hostname and Fail-Closed DNS IP checks.",
    )


def filter_safe_external_urls(
    urls: list[str],
    block_private_ips: bool = True,
    resolve_dns: bool = True,
    dns_resolver: Callable[[str], list[str]] | None = None,
    strict_dns_failure: bool = True,
) -> list[str]:
    """Filter a list of discovered RSS, press, or external source URLs, keeping only SSRF-safe URLs."""
    safe_urls: list[str] = []
    for u in urls:
        check = validate_url_ssrf(
            u,
            block_private_ips=block_private_ips,
            resolve_dns=resolve_dns,
            dns_resolver=dns_resolver,
            strict_dns_failure=strict_dns_failure,
        )
        if check.is_safe and check.url not in safe_urls:
            safe_urls.append(check.url)
    return safe_urls


def build_ip_pinned_url_and_headers(
    original_url: str,
    pinned_ip: str,
    base_headers: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Rewrite `original_url` to connect directly to `pinned_ip` while preserving the original `Host` header.

    Returns:
        (pinned_target_url, original_hostname, merged_headers_with_host)
    """
    parsed = urlparse(original_url)
    hostname = (parsed.hostname or "").lower().strip(".")
    port = parsed.port

    # Format IPv6 literal with brackets if needed
    clean_ip = pinned_ip.strip().strip("[]")
    ip_host_literal = f"[{clean_ip}]" if ":" in clean_ip else clean_ip

    pinned_netloc = f"{ip_host_literal}:{port}" if port else ip_host_literal
    original_host_header = f"{hostname}:{port}" if port else hostname

    pinned_url = urlunparse(
        (
            parsed.scheme,
            pinned_netloc,
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    merged_headers: dict[str, str] = dict(base_headers or {})
    merged_headers["Host"] = original_host_header
    return pinned_url, hostname, merged_headers


async def safe_http_get(
    url: str,
    client: httpx.AsyncClient,
    *,
    max_redirects: int = 5,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
    block_private_ips: bool = True,
    resolve_dns: bool = True,
    dns_resolver: Callable[[str], list[str]] | None = None,
    strict_dns_failure: bool = True,
    pin_resolved_ip: bool = True,
) -> httpx.Response:
    """Execute an HTTP GET request with Fail-Closed SSRF validation, IP pinning, and per-hop redirect checks.

    To eliminate DNS-Rebinding / TOCTOU vulnerabilities between `validate_url_ssrf` and socket connect:
    1. Resolves and validates the target hostname's IP address once per hop (`strict_dns_failure=True`).
    2. Binds the outgoing HTTPX request directly to the validated `pinned_ip` (`https://<pinned_ip>/...`).
    3. Preserves the original `Host` header (`Host: <hostname>[:port]`) and binds TLS SNI / X.509
       certificate hostname verification to the original hostname via `request.extensions["sni_hostname"]`.
    4. Restores `response.request.url` to the canonical `current_url` so downstream relative URL joins
       and source citations retain the original domain name.
    """
    current_url = url.strip()

    for hop in range(max_redirects + 1):
        check = validate_url_ssrf(
            current_url,
            block_private_ips=block_private_ips,
            resolve_dns=resolve_dns,
            dns_resolver=dns_resolver,
            strict_dns_failure=strict_dns_failure,
        )
        if not check.is_safe:
            raise SSRFBlockedError(check.reason)

        base_req_headers: dict[str, str] = dict(client.headers)
        if headers:
            base_req_headers.update(headers)

        if pin_resolved_ip and check.resolved_ips:
            pinned_ip = check.resolved_ips[0]
            target_url, orig_hostname, req_headers = build_ip_pinned_url_and_headers(
                current_url,
                pinned_ip=pinned_ip,
                base_headers=base_req_headers,
            )
            request = client.build_request(
                "GET",
                target_url,
                headers=req_headers,
                timeout=timeout if timeout is not None else client.timeout,
                extensions={
                    "sni_hostname": orig_hostname,
                    "pinned_ip": pinned_ip,
                    "logical_url": current_url,
                },
            )
        else:
            request = client.build_request(
                "GET",
                current_url,
                headers=base_req_headers,
                timeout=timeout if timeout is not None else client.timeout,
            )

        response = await client.send(request, follow_redirects=False)
        # Restore canonical logical URL on the request so response.url reflects original hostname
        response.request.url = httpx.URL(current_url)

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "").strip()
            if not location:
                return response
            if hop >= max_redirects:
                raise SSRFBlockedError(
                    f"Maximum redirect limit ({max_redirects}) exceeded starting from '{url}'."
                )
            next_url = urljoin(current_url, location)
            # Re-validate the redirect target URL & DNS (Fail-Closed) before following!
            redirect_check = validate_url_ssrf(
                next_url,
                block_private_ips=block_private_ips,
                resolve_dns=resolve_dns,
                dns_resolver=dns_resolver,
                strict_dns_failure=strict_dns_failure,
            )
            if not redirect_check.is_safe:
                raise SSRFBlockedError(
                    f"Redirect SSRF blocked from '{current_url}' -> '{next_url}': {redirect_check.reason}"
                )
            current_url = next_url
            continue

        return response

    raise SSRFBlockedError(f"Maximum redirect limit ({max_redirects}) exceeded for '{url}'.")
