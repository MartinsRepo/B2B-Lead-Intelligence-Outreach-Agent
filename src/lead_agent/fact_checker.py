"""5-Step Fact-Verification & Claim-Grounding Engine for LeadReport outputs."""

from __future__ import annotations

import re

import httpx

from lead_agent.config import DEFAULT_SETTINGS, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.schemas import LeadReport, SourceCitation, VerifiedClaim
from lead_agent.tools.web_scraper import DEFAULT_HEADERS, extract_clean_page_data

STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "their",
        "have",
        "has",
        "had",
        "are",
        "was",
        "were",
        "will",
        "would",
        "could",
        "should",
        "over",
        "under",
        "across",
        "through",
        "while",
        "about",
        "after",
        "before",
        "between",
        "during",
        "including",
        "also",
        "more",
        "most",
        "other",
        "some",
        "such",
        "than",
        "then",
        "them",
        "they",
        "these",
        "those",
        "very",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "your",
        "our",
        "its",
        "can",
        "may",
        "might",
        "must",
        "need",
        "needs",
        "new",
        "recent",
        "recently",
        "high",
        "low",
        "large",
        "small",
        "company",
        "enterprise",
        "business",
    }
)

HYPOTHESIS_PREFIX = "[Hypothesis / Inferred] "


def tokenize_meaningful_terms(text: str) -> list[str]:
    """Extract lowercase alphanumeric tokens (>=3 chars) excluding common stopwords."""
    raw_tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9.+#-]{1,}", text.lower())
    result: list[str] = []
    for tok in raw_tokens:
        cleaned = tok.strip(".-")
        if len(cleaned) >= 3 and cleaned not in STOPWORDS:
            result.append(cleaned)
    return result


def split_into_passages(source_text: str, window_size: int = 2) -> list[str]:
    """Split source document text into 1-2 sentence windows for passage retrieval."""
    cleaned = " ".join(source_text.split())
    if not cleaned:
        return []
    raw_sentences = re.split(r"(?<=[.!?])\s+|\s+[|—•]\s+", cleaned)
    sentences = [s.strip() for s in raw_sentences if len(s.strip()) >= 15]
    if not sentences:
        return [cleaned[:450]]

    passages: list[str] = []
    for idx in range(len(sentences)):
        window = " ".join(sentences[idx : idx + window_size]).strip()
        if window:
            passages.append(window[:500])
    return passages


def extract_best_matching_passage(claim: str, source_text: str) -> tuple[str, float]:
    """Step 3 & 4: Find the passage in `source_text` that best supports `claim` and score overlap."""
    claim_tokens = tokenize_meaningful_terms(claim)
    if not claim_tokens or not source_text.strip():
        return "", 0.0

    claim_set = set(claim_tokens)
    # Give extra weight to numbers, acronyms, and specific technical/product terms (>=6 chars)
    high_signal_tokens = {
        t for t in claim_set if any(c.isdigit() for c in t) or len(t) >= 6
    }

    passages = split_into_passages(source_text)
    best_passage = ""
    best_score = 0.0

    for passage in passages:
        passage_tokens = set(tokenize_meaningful_terms(passage))
        if not passage_tokens:
            continue

        # Direct token match + prefix stem match (e.g. "metering" <-> "meter", "launched" <-> "launch")
        matched_tokens: set[str] = set()
        for c_tok in claim_set:
            if c_tok in passage_tokens:
                matched_tokens.add(c_tok)
            elif len(c_tok) >= 5:
                stem = c_tok[:5]
                if any(p_tok.startswith(stem) for p_tok in passage_tokens):
                    matched_tokens.add(c_tok)

        base_recall = len(matched_tokens) / max(len(claim_set), 1)
        high_signal_hits = len(matched_tokens & high_signal_tokens)
        high_signal_bonus = min(0.25, high_signal_hits * 0.08)

        score = round(min(1.0, base_recall + high_signal_bonus), 2)
        if score > best_score:
            best_score = score
            best_passage = passage

    if not best_passage and passages:
        best_passage = passages[0][:350]

    return best_passage, best_score


def select_best_source_for_claim(
    claim: str,
    sources: list[SourceCitation],
    refetched_corpus: dict[str, str],
) -> tuple[SourceCitation, str, float]:
    """Step 1: Assign a claim to the source whose re-fetched text best supports it."""
    best_source = sources[0]
    best_passage = best_source.snippet
    best_score = -1.0

    for src in sources:
        full_text = refetched_corpus.get(src.url, "")
        combined_corpus = f"{src.title}. {src.snippet}. {full_text}".strip()
        passage, score = extract_best_matching_passage(claim, combined_corpus)
        if score > best_score:
            best_score = score
            best_source = src
            best_passage = passage or src.snippet

    return best_source, best_passage, max(0.0, best_score)


def classify_verification_status(
    grounding_score: float,
    min_grounding_score: float = 0.25,
) -> str:
    """Classify a claim based on its grounding score against the original source passage."""
    verified_cutoff = max(0.45, min_grounding_score + 0.15)
    if grounding_score >= verified_cutoff:
        return "verified"
    if grounding_score >= min_grounding_score:
        return "partially_supported"
    return "inferred_hypothesis"


async def refetch_sources_corpus(
    sources: list[SourceCitation],
    timeout: float = 8.0,
    custom_fetcher: object | None = None,
) -> dict[str, str]:
    """Step 2: Re-fetch each cited source URL to retrieve the original full-text corpus."""
    corpus: dict[str, str] = {}
    if custom_fetcher is not None and callable(custom_fetcher):
        for src in sources:
            corpus[src.url] = str(await custom_fetcher(src.url))
        return corpus

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        for src in sources[:6]:
            if src.url in corpus:
                continue
            try:
                resp = await client.get(src.url)
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    page_data = extract_clean_page_data(resp.text, str(resp.url), max_chars=5000)
                    headings_str = ". ".join(
                        str(h) for h in (page_data.get("headings") or [])  # type: ignore[union-attr]
                    )
                    corpus[src.url] = (
                        f"{page_data.get('title', '')}. "
                        f"{page_data.get('meta_description', '')}. "
                        f"{headings_str}. "
                        f"{page_data.get('body_excerpt', '')}"
                    ).strip()
                else:
                    corpus[src.url] = f"{src.title}. {src.snippet}"
            except Exception:
                # Fallback to captured source title & snippet if network re-fetch fails
                corpus[src.url] = f"{src.title}. {src.snippet}"

    return corpus


def _apply_unverified_policy_to_claims(
    claims_list: list[str],
    verified_records: list[VerifiedClaim],
    policy: str,
) -> list[str]:
    """Step 5: Either mark unverified claims as '[Hypothesis / Inferred]' or discard them."""
    status_by_claim = {r.claim: r.verification_status for r in verified_records}
    updated: list[str] = []

    for claim_text in claims_list:
        clean_claim = claim_text.removeprefix(HYPOTHESIS_PREFIX).strip()
        status = status_by_claim.get(claim_text) or status_by_claim.get(clean_claim, "verified")

        if status == "inferred_hypothesis":
            if policy == "discard":
                continue
            # Default: mark_as_hypothesis
            if not claim_text.startswith(HYPOTHESIS_PREFIX):
                updated.append(f"{HYPOTHESIS_PREFIX}{claim_text}")
            else:
                updated.append(claim_text)
        else:
            updated.append(claim_text)

    # Ensure at least one item remains so LeadReport(min_length=1) schema stays valid
    if not updated and claims_list:
        first = claims_list[0].removeprefix(HYPOTHESIS_PREFIX).strip()
        updated.append(f"{HYPOTHESIS_PREFIX}{first}")

    return updated


async def verify_and_ground_lead_report(
    report: LeadReport,
    settings: AgentSettings = DEFAULT_SETTINGS,
    run_context: LeadRunContext | None = None,
    custom_fetcher: object | None = None,
) -> LeadReport:
    """Execute the 5-step fact verification pipeline on a LeadReport."""
    if not settings.enable_fact_checking or not report.sources:
        return report

    if run_context is not None:
        run_context.log_tool_event(
            f"Fact-Checker -> Re-fetching {len(report.sources)} cited source(s) for claim verification"
        )

    # Step 2: Re-fetch the cited source documents
    refetched_corpus = await refetch_sources_corpus(
        report.sources,
        timeout=min(settings.http_timeout_seconds, 8.0),
        custom_fetcher=custom_fetcher,
    )

    verified_claims: list[VerifiedClaim] = []
    all_claims: list[tuple[str, str]] = [
        (c, "news_trigger") for c in report.recent_news_and_triggers
    ] + [
        (p, "pain_point") for p in report.identified_pain_points
    ]

    # Steps 1, 3, 4: Match each claim to a source, extract passage, and compare
    for raw_claim, category in all_claims:
        clean_claim = raw_claim.removeprefix(HYPOTHESIS_PREFIX).strip()
        matched_src, passage, score = select_best_source_for_claim(
            clean_claim, report.sources, refetched_corpus
        )
        status = classify_verification_status(
            score, min_grounding_score=settings.min_grounding_score
        )
        verified_claims.append(
            VerifiedClaim(
                claim=clean_claim,
                category=category,
                source_title=matched_src.title,
                source_url=matched_src.url,
                matched_excerpt=passage[:380],
                grounding_score=score,
                verification_status=status,
            )
        )

    # Step 5: Mark unverifiable claims as hypotheses or discard them
    updated_news = _apply_unverified_policy_to_claims(
        report.recent_news_and_triggers,
        [vc for vc in verified_claims if vc.category == "news_trigger"],
        policy=settings.unverified_claim_policy,
    )
    updated_pains = _apply_unverified_policy_to_claims(
        report.identified_pain_points,
        [vc for vc in verified_claims if vc.category == "pain_point"],
        policy=settings.unverified_claim_policy,
    )

    if run_context is not None:
        verified_count = sum(
            1 for vc in verified_claims if vc.verification_status in {"verified", "partially_supported"}
        )
        hypothesis_count = sum(
            1 for vc in verified_claims if vc.verification_status == "inferred_hypothesis"
        )
        run_context.log_tool_event(
            f"Fact-Checker -> {verified_count}/{len(verified_claims)} claims grounded in source text "
            f"({hypothesis_count} flagged as hypothesis, policy='{settings.unverified_claim_policy}')"
        )

    return report.model_copy(
        update={
            "recent_news_and_triggers": updated_news,
            "identified_pain_points": updated_pains,
            "verified_claims": verified_claims,
        }
    )
