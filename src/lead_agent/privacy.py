"""GDPR / DSGVO Privacy, PII Redaction, Data Minimization, Retention, and Art. 21 Opt-Out Engine."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# 1. PII Regex Patterns for Redaction (Art. 5(1)(c) Data Minimization)
EMAIL_PII_REGEX = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,24}\b"
)

# International and domestic phone/mobile/fax numbers (e.g. +49 (0) 89 12345-67, +1-555-234-5678, Tel: 089/123456)
PHONE_PII_REGEX = re.compile(
    r"(?:(?:tel|phone|fon|fax|mobil|mobile|call)[:\s]+)?(?:\+\d{1,3}[\s.-]?)?(?:\(0\)[\s.-]?)?(?:\(?\d{2,5}\)?[\s./-]{1,2})\d{3,5}[\s./-]?\d{2,6}\b",
    re.IGNORECASE,
)

# Personal social/LinkedIn profile paths (e.g. linkedin.com/in/john-doe-12345)
PERSONAL_LINKEDIN_REGEX = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[a-zA-Z0-9_%-]+/?",
    re.IGNORECASE,
)

# Explicit HR / Recruiter / Press Contact Person patterns (German & English)
CONTACT_PERSON_REGEX = re.compile(
    r"\b(?:"
    r"ansprechpartner(?:in)?|kontaktperson|ihr(?:e)?\s+ansprechpartner(?:in)?|"
    r"recruiter(?:in)?|talent\s+acquisition\s+contact|press\s+contact|media\s+contact|"
    r"your\s+contact(?:\s+person)?|written\s+by|authored\s+by"
    r")\s*[:\-–]?\s*"
    r"(?:(?:herr|frau|mr\.?|mrs\.?|ms\.?|dr\.?|prof\.?)\s+)*"
    r"[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,2}",
    re.IGNORECASE,
)

# Honorific + Full Name pattern (e.g. "Herr Dr. Thomas Müller", "Frau Julia Schmidt", "Mr. John Smith")
HONORIFIC_NAME_REGEX = re.compile(
    r"\b(?:[Hh]err|[Ff]rau|[Mm]r\.?|[Mm]rs\.?|[Mm]s\.?)\s+(?:(?:[Dd]r\.?|[Pp]rof\.?)\s+)*[A-ZÄÖÜ][a-zäöüß]+\s+[A-ZÄÖÜ][a-zäöüß\-]+\b"
)

# DOM selectors that commonly contain personal employee/author/recruiter data
PII_DOM_SELECTORS: tuple[str, ...] = (
    "author",
    "address",
    "[rel='author']",
    "[itemprop='author']",
    "[itemprop='employee']",
    "[itemprop='founder']",
    ".author",
    ".author-bio",
    ".byline",
    ".vcard",
    ".team-member",
    ".recruiter",
    ".contact-person",
    ".press-contact",
)


def strip_personal_dom_elements(soup: BeautifulSoup) -> None:
    """Remove DOM elements and meta tags that typically hold personal author/employee PII."""
    for selector in PII_DOM_SELECTORS:
        try:
            for el in soup.select(selector):
                el.decompose()
        except Exception:
            continue

    for meta in soup.find_all("meta"):
        meta_name = str(meta.get("name") or meta.get("property") or "").lower()
        if any(
            k in meta_name
            for k in ("author", "creator", "article:author", "twitter:creator")
        ):
            meta.decompose()


def scrub_personal_data(text: str, redact_emails: bool = True, redact_phones: bool = True) -> str:
    """Scrub personal data (PII) such as emails, phone numbers, personal profiles, and contact names."""
    if not text:
        return ""

    cleaned = text
    cleaned = PERSONAL_LINKEDIN_REGEX.sub("[REDACTED_PERSONAL_PROFILE]", cleaned)
    cleaned = CONTACT_PERSON_REGEX.sub("[REDACTED_CONTACT_PERSON]", cleaned)
    cleaned = HONORIFIC_NAME_REGEX.sub("[REDACTED_PERSON_NAME]", cleaned)

    if redact_emails:
        cleaned = EMAIL_PII_REGEX.sub("[REDACTED_EMAIL]", cleaned)

    if redact_phones:
        cleaned = PHONE_PII_REGEX.sub("[REDACTED_PHONE]", cleaned)

    return cleaned


def is_personal_profile_url(raw_url_or_input: str) -> bool:
    """Return True if the input URL points to an individual person's profile (e.g. linkedin.com/in/...)."""
    return bool(PERSONAL_LINKEDIN_REGEX.search(raw_url_or_input.strip()))


def minimize_corporate_text(
    text: str,
    max_chars: int = 4000,
    redact_pii: bool = True,
) -> str:
    """Apply GDPR Art. 5(1)(c) data minimization and PII redaction to corporate webpage text."""
    scrubbed = scrub_personal_data(text) if redact_pii else text
    normalized = " ".join(scrubbed.split())
    return normalized[:max_chars]


def normalize_domain_key(url_or_domain: str) -> str:
    """Extract normalized lowercase domain name (without www.) from a domain or URL."""
    cleaned = url_or_domain.strip().lower()
    if not cleaned:
        return ""
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower().strip(".").removeprefix("www.")
    return host


class OptOutBlocklistManager:
    """Art. 21 GDPR & § 7 UWG Right to Object (Widerspruchs- und Sperrlistenmechanismus).

    Blocks analysis, scraping, and outreach generation for any domain that has objected
    or been added to the permanent compliance blocklist.
    """

    def __init__(
        self,
        initial_domains: set[str] | list[str] | tuple[str, ...] | None = None,
        storage_path: Path | str | None = None,
    ) -> None:
        self._storage_path = Path(storage_path) if storage_path else None
        self._domains: set[str] = set()
        self._objection_timestamps: dict[str, str] = {}

        env_domains = os.getenv("GDPR_OPT_OUT_DOMAINS", "")
        for d in env_domains.split(","):
            norm = normalize_domain_key(d)
            if norm:
                self._domains.add(norm)

        if initial_domains:
            for d in initial_domains:
                norm = normalize_domain_key(d)
                if norm:
                    self._domains.add(norm)

        if self._storage_path and self._storage_path.exists():
            try:
                data = json.loads(self._storage_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        norm = normalize_domain_key(str(item))
                        if norm:
                            self._domains.add(norm)
                elif isinstance(data, dict):
                    for item in data.get("blocked_domains", []):
                        norm = normalize_domain_key(str(item))
                        if norm:
                            self._domains.add(norm)
                    raw_ts = data.get("objection_timestamps", {})
                    if isinstance(raw_ts, dict):
                        for k, v in raw_ts.items():
                            norm = normalize_domain_key(str(k))
                            if norm:
                                self._domains.add(norm)
                                self._objection_timestamps[norm] = str(v)
            except Exception:
                pass

    @property
    def blocked_domains(self) -> tuple[str, ...]:
        """Return sorted tuple of currently blocked/opted-out domains."""
        return tuple(sorted(self._domains))

    @property
    def objection_records(self) -> dict[str, str]:
        """Return mapping of permanently opted-out domains to their UTC objection timestamp."""
        return dict(self._objection_timestamps)

    def add_domain(self, url_or_domain: str, objected_at_utc: str | None = None) -> str:
        """Add a domain to the permanent Art. 21 GDPR / § 7 UWG opt-out blocklist and persist."""
        norm = normalize_domain_key(url_or_domain)
        if not norm:
            raise ValueError("Cannot add an empty domain to the Art. 21 opt-out blocklist.")
        self._domains.add(norm)
        self._objection_timestamps[norm] = objected_at_utc or datetime.now(UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self._persist()
        return norm

    def sync_domains(self, domains: set[str] | list[str] | tuple[str, ...]) -> None:
        """Synchronize runtime opt-out domains into the manager and persist permanently."""
        changed = False
        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for d in domains:
            norm = normalize_domain_key(d)
            if norm and norm not in self._domains:
                self._domains.add(norm)
                self._objection_timestamps.setdefault(norm, now_str)
                changed = True
        if changed:
            self._persist()

    def remove_domain(self, url_or_domain: str) -> str:
        """Remove a domain from the opt-out blocklist."""
        norm = normalize_domain_key(url_or_domain)
        self._domains.discard(norm)
        self._objection_timestamps.pop(norm, None)
        self._persist()
        return norm

    def is_opted_out(self, url_or_domain: str) -> tuple[bool, str]:
        """Check whether `url_or_domain` (or its parent domain) is on the Art. 21 / § 7 UWG opt-out blocklist."""
        host = normalize_domain_key(url_or_domain)
        if not host:
            return False, ""
        for blocked in self._domains:
            if host == blocked or host.endswith(f".{blocked}"):
                return (
                    True,
                    f"Domain '{host}' is permanently blocked due to an Art. 21 GDPR / § 7 UWG opt-out blocklist entry ('{blocked}').",
                )
        return False, ""

    def _persist(self) -> None:
        if self._storage_path is not None:
            try:
                self._storage_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "blocked_domains": sorted(self._domains),
                    "objection_timestamps": {
                        k: self._objection_timestamps[k]
                        for k in sorted(self._objection_timestamps)
                        if k in self._domains
                    },
                }
                self._storage_path.write_text(
                    json.dumps(payload, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass


def compute_retention_timestamps(
    ttl_seconds: int = 3600,
    now_utc: datetime | None = None,
) -> tuple[str, str]:
    """Compute ISO-8601 UTC `(created_at_utc, expires_at_utc)` timestamps for a LeadReport."""
    now = now_utc or datetime.now(UTC)
    expires = now + timedelta(seconds=max(0, ttl_seconds))
    return (
        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def is_timestamp_expired(
    expires_at_utc: str,
    now_utc: datetime | None = None,
) -> bool:
    """Return True if the ISO-8601 UTC expiration timestamp has passed."""
    if not expires_at_utc.strip():
        return False
    now = now_utc or datetime.now(UTC)
    try:
        cleaned = expires_at_utc.strip().replace("Z", "+00:00")
        exp_dt = datetime.fromisoformat(cleaned)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=UTC)
        return now >= exp_dt
    except ValueError:
        return False


def get_art14_outreach_footer(company_name: str = "your organization") -> str:
    """Return a concise GDPR Art. 14 transparency and Art. 21 opt-out notice for B2B outreach."""
    return (
        f"Transparency Notice (Art. 14 GDPR / DSGVO): The context for this message was derived solely "
        f"from publicly accessible corporate information published by {company_name} (no personal profile "
        "profiling). You may object to future B2B communication at any time (Art. 21 GDPR) to be placed on "
        "our permanent domain opt-out blocklist."
    )


DEFAULT_OPT_OUT_STORAGE_PATH = Path(
    os.getenv(
        "GDPR_OPT_OUT_STORAGE_PATH",
        str(Path(__file__).resolve().parents[2] / ".gdpr_opt_out_blocklist.json"),
    )
)

DEFAULT_OPT_OUT_MANAGER = OptOutBlocklistManager(
    storage_path=DEFAULT_OPT_OUT_STORAGE_PATH
)

# Misleading or unsubstantiated advertising claims prohibited under § 5 UWG (Irreführende geschäftliche Handlungen)
DEFAULT_MISLEADING_ADVERTISING_PHRASES: tuple[str, ...] = (
    "100% guaranteed",
    "guaranteed roi",
    "guaranteed revenue",
    "zero risk",
    "risk-free guarantee",
    "certifiably the #1",
    "proven to double",
    "eliminates all downtime",
    "100% bug-free",
    "officially endorsed by",
    "exclusive partnership with",
)


def detect_misleading_advertising_claims(
    text: str,
    prohibited_phrases: tuple[str, ...] = DEFAULT_MISLEADING_ADVERTISING_PHRASES,
) -> list[str]:
    """Detect misleading, deceptive, or unsubstantiated superlative advertising claims (§ 5 UWG)."""
    if not text:
        return []
    lower_text = text.lower()
    violations: list[str] = []
    for phrase in prohibited_phrases:
        cleaned = phrase.strip().lower()
        if cleaned and cleaned in lower_text:
            violations.append(phrase)
    return violations
