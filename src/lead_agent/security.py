"""SSRF protection, DNS resolution verification, and redirect-safe HTTP client utilities."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

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
    """Result of an SSRF URL and DNS validation check."""

    is_safe: bool
    url: str
    resolved_ips: tuple[str, ...]
    reason: str


def is_ip_blocked(ip_str: str) -> tuple[bool, str]:
    """Check whether an IPv4 or IPv6 address belongs to any private, loopback, link-local, or reserved range."""
    cleaned = ip_str.strip().strip("[]")
    # Strip IPv6 zone index if present (e.g. fe80::1%eth0)
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
    strict_dns_failure: bool = False,
) -> SSRFCheckOutcome:
    """Validate a URL against SSRF vectors including scheme, hostname, IP ranges, and DNS resolution."""
    cleaned = url.strip()
    if not cleaned:
        return SSRFCheckOutcome(
            is_safe=False,
            url="",
            resolved_ips=(),
            reason="URL cannot be empty.",
        )

    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return SSRFCheckOutcome(
            is_safe=False,
            url=cleaned,
            resolved_ips=(),
            reason=f"Unsupported or unsafe URL scheme '{scheme}'. Only http:// and https:// are permitted.",
        )

    hostname = (parsed.hostname or "").lower().strip(".")
    if not hostname:
        return SSRFCheckOutcome(
            is_safe=False,
            url=cleaned,
            resolved_ips=(),
            reason=f"URL '{cleaned}' does not contain a valid hostname.",
        )

    if not block_private_ips:
        return SSRFCheckOutcome(
            is_safe=True,
            url=cleaned,
            resolved_ips=(),
            reason="Private IP blocking disabled by configuration.",
        )

    # 1. Check literal IP address hostnames first (e.g. http://127.0.0.1, http://169.254.169.254, http://[::1])
    try:
        ipaddress.ip_address(hostname.strip("[]"))
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False

    if is_literal_ip:
        blocked, ip_reason = is_ip_blocked(hostname)
        if blocked:
            return SSRFCheckOutcome(
                is_safe=False,
                url=cleaned,
                resolved_ips=(hostname,),
                reason=f"SSRF Guardrail blocked literal IP host '{hostname}': {ip_reason}",
            )
        return SSRFCheckOutcome(
            is_safe=True,
            url=cleaned,
            resolved_ips=(hostname,),
            reason="Literal IP host is public.",
        )

    # 2. Check blocked internal/local hostnames and suffixes
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(BLOCKED_HOSTNAME_SUFFIXES):
        return SSRFCheckOutcome(
            is_safe=False,
            url=cleaned,
            resolved_ips=(),
            reason=f"Host '{hostname}' is a private/local address and is blocked by the SSRF Guardrail.",
        )

    # 3. Resolve DNS (A/AAAA records) and verify every resolved IP is public
    resolved_ips: list[str] = []
    if resolve_dns:
        resolver_fn = dns_resolver or resolve_hostname_ips
        try:
            resolved_ips = resolver_fn(hostname)
        except socket.gaierror as exc:
            if strict_dns_failure:
                return SSRFCheckOutcome(
                    is_safe=False,
                    url=cleaned,
                    resolved_ips=(),
                    reason=f"DNS resolution failed for host '{hostname}': {exc!s}",
                )
            resolved_ips = []
        except Exception as exc:
            if strict_dns_failure:
                return SSRFCheckOutcome(
                    is_safe=False,
                    url=cleaned,
                    resolved_ips=(),
                    reason=f"DNS lookup error for host '{hostname}': {exc!s}",
                )
            resolved_ips = []

        for ip_addr in resolved_ips:
            blocked, ip_reason = is_ip_blocked(ip_addr)
            if blocked:
                return SSRFCheckOutcome(
                    is_safe=False,
                    url=cleaned,
                    resolved_ips=tuple(resolved_ips),
                    reason=(
                        f"SSRF DNS Guardrail blocked host '{hostname}' because it resolved to "
                        f"non-public IP '{ip_addr}': {ip_reason}"
                    ),
                )

    return SSRFCheckOutcome(
        is_safe=True,
        url=cleaned,
        resolved_ips=tuple(resolved_ips),
        reason="URL passed all SSRF hostname and DNS IP checks.",
    )


def filter_safe_external_urls(
    urls: list[str],
    block_private_ips: bool = True,
    resolve_dns: bool = True,
    dns_resolver: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Filter a list of discovered RSS, press, or external source URLs, keeping only SSRF-safe URLs."""
    safe_urls: list[str] = []
    for u in urls:
        check = validate_url_ssrf(
            u,
            block_private_ips=block_private_ips,
            resolve_dns=resolve_dns,
            dns_resolver=dns_resolver,
        )
        if check.is_safe and check.url not in safe_urls:
            safe_urls.append(check.url)
    return safe_urls


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
) -> httpx.Response:
    """Execute an HTTP GET request with full SSRF pre-validation and per-hop redirect re-validation.

    Every redirect target (`301`, `302`, `303`, `307`, `308`) is validated against `validate_url_ssrf`
    (including DNS resolution to private/reserved IP networks) before the redirect is followed.
    """
    current_url = url.strip()

    for hop in range(max_redirects + 1):
        check = validate_url_ssrf(
            current_url,
            block_private_ips=block_private_ips,
            resolve_dns=resolve_dns,
            dns_resolver=dns_resolver,
        )
        if not check.is_safe:
            raise SSRFBlockedError(check.reason)

        request_kwargs: dict[str, object] = {"follow_redirects": False}
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        if headers is not None:
            request_kwargs["headers"] = headers

        response = await client.get(current_url, **request_kwargs)  # type: ignore[arg-type]

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "").strip()
            if not location:
                return response
            if hop >= max_redirects:
                raise SSRFBlockedError(
                    f"Maximum redirect limit ({max_redirects}) exceeded starting from '{url}'."
                )
            next_url = urljoin(str(response.url), location)
            # Re-validate the redirect target URL & DNS before following!
            redirect_check = validate_url_ssrf(
                next_url,
                block_private_ips=block_private_ips,
                resolve_dns=resolve_dns,
                dns_resolver=dns_resolver,
            )
            if not redirect_check.is_safe:
                raise SSRFBlockedError(
                    f"Redirect SSRF blocked from '{current_url}' -> '{next_url}': {redirect_check.reason}"
                )
            current_url = next_url
            continue

        return response

    raise SSRFBlockedError(f"Maximum redirect limit ({max_redirects}) exceeded for '{url}'.")
