"""5-Step Fact-Verification & Semantic Claim-Grounding Engine for LeadReport outputs."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import httpx

from lead_agent.config import DEFAULT_SETTINGS, AgentSettings
from lead_agent.context import LeadRunContext
from lead_agent.schemas import LeadReport, SourceCitation, VerifiedClaim
from lead_agent.security import safe_http_get
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
        "recent",
        "recently",
        "company",
        "enterprise",
        "business",
    }
)

NEGATION_TOKENS: frozenset[str] = frozenset(
    {
        "not",
        "no",
        "never",
        "neither",
        "nor",
        "without",
        "none",
        "lack",
        "lacks",
        "dropped",
        "abandoned",
        "discontinued",
        "false",
        "unlikely",
    }
)

# B2B Domain Semantic Concept Clusters for paraphrase & synonym matching
SEMANTIC_CONCEPT_CLUSTERS: dict[str, frozenset[str]] = {
    "CONCEPT_LAUNCH_RELEASE": frozenset(
        {"launch", "launched", "launches", "release", "released", "announces", "announced", "unveiled", "introduced", "rollout", "debut", "milestone"}
    ),
    "CONCEPT_CLOUD_INFRA": frozenset(
        {"cloud", "aws", "azure", "gcp", "kubernetes", "k8s", "docker", "container", "cluster", "clusters", "serverless", "infrastructure", "terraform", "multi-region"}
    ),
    "CONCEPT_DATA_STREAMING": frozenset(
        {"kafka", "snowflake", "databricks", "spark", "streaming", "stream", "event", "events", "events/sec", "pipeline", "pipelines", "connector", "ingestion", "telemetry", "observability", "datadog"}
    ),
    "CONCEPT_LATENCY_PERFORMANCE": frozenset(
        {"latency", "throughput", "performance", "scalability", "scale", "scaling", "bottleneck", "bottlenecks", "overhead", "fast", "sub-second", "real-time", "replication", "velocity"}
    ),
    "CONCEPT_AI_ML": frozenset(
        {"ai", "llm", "llms", "machine", "learning", "ml", "pytorch", "openai", "agent", "agents", "agentic", "inference", "model", "models", "generative", "automation"}
    ),
    "CONCEPT_FINTECH_BILLING": frozenset(
        {"payment", "payments", "fintech", "billing", "metering", "usage-based", "revenue", "financial", "transaction", "transactions", "checkout", "ledger", "cost", "costs", "finops", "spend"}
    ),
    "CONCEPT_EV_AUTOMOTIVE": frozenset(
        {"automotive", "vehicle", "vehicles", "ev", "electric", "mobility", "car", "cars", "fleet", "manufacturing", "production", "plant", "battery", "autonomous"}
    ),
    "CONCEPT_FRONTEND_WEB": frozenset(
        {"react", "next.js", "nextjs", "typescript", "javascript", "vue", "frontend", "web", "ui", "ssr", "vercel", "tailwind"}
    ),
    "CONCEPT_HIRING_ENGINEERING": frozenset(
        {"hiring", "hire", "careers", "job", "jobs", "engineer", "engineers", "engineering", "developer", "architect", "staff", "senior", "recruiting", "role", "roles", "team"}
    ),
    "CONCEPT_SECURITY_COMPLIANCE": frozenset(
        {"security", "compliance", "soc2", "iso", "gdpr", "audit", "zero-trust", "encryption", "governance", "waf", "fraud", "risk"}
    ),
}

HYPOTHESIS_PREFIX = "[Hypothesis / Inferred] "
PARTIALLY_SUPPORTED_PREFIX = "[Partially Supported] "


@dataclass(frozen=True)
class RefetchedSourceDocument:
    """Result of re-fetching a cited source URL during fact verification."""

    url: str
    text: str
    refetch_succeeded: bool
    status_code: int = 0


def strip_status_prefixes(text: str) -> str:
    """Remove existing verification status prefixes from a claim string."""
    cleaned = text.strip()
    for prefix in (HYPOTHESIS_PREFIX, PARTIALLY_SUPPORTED_PREFIX):
        if cleaned.startswith(prefix):
            cleaned = cleaned.removeprefix(prefix).strip()
    return cleaned


def tokenize_meaningful_terms(text: str) -> list[str]:
    """Extract lowercase alphanumeric tokens (>=3 chars) excluding common stopwords."""
    raw_tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9.+#/-]{1,}", text.lower())
    result: list[str] = []
    for tok in raw_tokens:
        cleaned = tok.strip(".-/")
        if len(cleaned) >= 2 and cleaned not in STOPWORDS:
            result.append(cleaned)
    return result


def extract_semantic_concepts(tokens: set[str]) -> set[str]:
    """Map tokens and token stems to canonical B2B semantic concept clusters."""
    concepts: set[str] = set()
    for concept_name, cluster_words in SEMANTIC_CONCEPT_CLUSTERS.items():
        if tokens & cluster_words:
            concepts.add(concept_name)
            continue
        # Check 5-char stem match against cluster words
        for tok in tokens:
            if len(tok) >= 5 and any(cw.startswith(tok[:5]) for cw in cluster_words):
                concepts.add(concept_name)
                break
    return concepts


def _char_ngram_cosine(text_a: str, text_b: str, n: int = 3) -> float:
    """Compute character n-gram cosine similarity between two strings (0.0 to 1.0)."""
    norm_a = re.sub(r"\s+", " ", text_a.lower().strip())
    norm_b = re.sub(r"\s+", " ", text_b.lower().strip())
    if len(norm_a) < n or len(norm_b) < n:
        return 0.0

    vec_a = Counter(norm_a[i : i + n] for i in range(len(norm_a) - n + 1))
    vec_b = Counter(norm_b[i : i + n] for i in range(len(norm_b) - n + 1))

    intersection = set(vec_a.keys()) & set(vec_b.keys())
    numerator = sum(vec_a[k] * vec_b[k] for k in intersection)
    if numerator == 0:
        return 0.0

    sum_a = sum(v * v for v in vec_a.values())
    sum_b = sum(v * v for v in vec_b.values())
    denom = math.sqrt(sum_a) * math.sqrt(sum_b)
    return numerator / denom if denom > 0 else 0.0


def _has_negation_mismatch(claim: str, passage: str) -> bool:
    """Return True if one statement contains explicit negation tokens while the other is affirmative."""
    claim_words = set(re.findall(r"[a-zA-Z]+", claim.lower()))
    passage_words = set(re.findall(r"[a-zA-Z]+", passage.lower()))
    claim_neg = bool(claim_words & NEGATION_TOKENS)
    passage_neg = bool(passage_words & NEGATION_TOKENS)
    return claim_neg != passage_neg


def compute_semantic_similarity(claim: str, passage: str) -> float:
    """Compute hybrid semantic similarity combining concept clusters, stem recall, n-grams, and negation check."""
    claim_tokens = set(tokenize_meaningful_terms(claim))
    passage_tokens = set(tokenize_meaningful_terms(passage))
    if not claim_tokens or not passage_tokens:
        return 0.0

    # 1. Semantic Concept Cluster Alignment
    claim_concepts = extract_semantic_concepts(claim_tokens)
    passage_concepts = extract_semantic_concepts(passage_tokens)
    if claim_concepts:
        concept_overlap = len(claim_concepts & passage_concepts) / len(claim_concepts)
    else:
        concept_overlap = 0.0

    # 2. Stem & Synonym-Expanded Token Recall
    matched_count = 0
    for c_tok in claim_tokens:
        if c_tok in passage_tokens:
            matched_count += 1
        elif len(c_tok) >= 5 and any(p_tok.startswith(c_tok[:5]) for p_tok in passage_tokens):
            matched_count += 1
        else:
            # Check if c_tok shares a semantic concept cluster with any token in passage_tokens
            tok_concepts = extract_semantic_concepts({c_tok})
            if tok_concepts and (tok_concepts & passage_concepts):
                matched_count += 0.75  # type: ignore[assignment]

    expanded_recall = min(1.0, matched_count / max(len(claim_tokens), 1))

    # 3. Character 3-gram Cosine Similarity
    ngram_sim = _char_ngram_cosine(claim, passage, n=3)

    raw_semantic = (expanded_recall * 0.50) + (concept_overlap * 0.30) + (ngram_sim * 0.20)

    # 4. Contradiction / Negation Penalty
    if _has_negation_mismatch(claim, passage):
        raw_semantic *= 0.35

    return round(min(1.0, max(0.0, raw_semantic)), 2)


def split_into_passages(source_text: str, window_size: int = 2) -> list[str]:
    """Split source document text into 1-2 sentence windows for passage retrieval."""
    cleaned = " ".join(source_text.split())
    if not cleaned:
        return []
    raw_sentences = re.split(r"(?<=[.!?])\s+|\s+[|—•]\s+", cleaned)
    sentences = [s.strip() for s in raw_sentences if len(s.strip()) >= 12]
    if not sentences:
        return [cleaned[:450]]

    passages: list[str] = []
    for idx in range(len(sentences)):
        window = " ".join(sentences[idx : idx + window_size]).strip()
        if window:
            passages.append(window[:500])
    return passages


def extract_best_matching_passage(
    claim: str, source_text: str
) -> tuple[str, float, float]:
    """Steps 3 & 4: Find the passage in `source_text` that best supports `claim`.

    Returns:
        (best_passage, grounding_score, semantic_score)
    """
    claim_tokens = tokenize_meaningful_terms(claim)
    if not claim_tokens or not source_text.strip():
        return "", 0.0, 0.0

    claim_set = set(claim_tokens)
    high_signal_tokens = {
        t for t in claim_set if any(c.isdigit() for c in t) or len(t) >= 6
    }

    passages = split_into_passages(source_text)
    best_passage = ""
    best_grounding = 0.0
    best_semantic = 0.0

    for passage in passages:
        passage_tokens = set(tokenize_meaningful_terms(passage))
        if not passage_tokens:
            continue

        matched_tokens: set[str] = set()
        for c_tok in claim_set:
            if c_tok in passage_tokens:
                matched_tokens.add(c_tok)
            elif len(c_tok) >= 5:
                stem = c_tok[:5]
                if any(p_tok.startswith(stem) for p_tok in passage_tokens):
                    matched_tokens.add(c_tok)

        lexical_recall = len(matched_tokens) / max(len(claim_set), 1)
        high_signal_hits = len(matched_tokens & high_signal_tokens)
        high_signal_bonus = min(0.12, high_signal_hits * 0.04)

        semantic_sim = compute_semantic_similarity(claim, passage)

        # Combine lexical recall (55%) + semantic similarity (35%) + high-signal bonus,
        # capped by token coverage so claims with many unsupported specifics remain 'partially_supported'
        combined_score = (lexical_recall * 0.55) + (semantic_sim * 0.35) + high_signal_bonus
        coverage_cap = lexical_recall + 0.15
        combined_score = min(combined_score, coverage_cap)
        if _has_negation_mismatch(claim, passage):
            combined_score *= 0.35

        grounding_score = round(min(1.0, combined_score), 2)
        if grounding_score > best_grounding:
            best_grounding = grounding_score
            best_semantic = semantic_sim
            best_passage = passage

    if not best_passage and passages:
        best_passage = passages[0][:350]

    return best_passage, best_grounding, best_semantic


def select_best_source_for_claim(
    claim: str,
    sources: list[SourceCitation],
    refetched_corpus: dict[str, RefetchedSourceDocument],
) -> tuple[SourceCitation, str, float, float, bool]:
    """Step 1: Assign a claim to the source whose re-fetched text best supports it.

    Returns:
        (best_source, best_passage, grounding_score, semantic_score, source_refetched)
    """
    best_source = sources[0]
    best_passage = best_source.snippet
    best_grounding = -1.0
    best_semantic = 0.0
    best_refetched = False

    for src in sources:
        doc = refetched_corpus.get(src.url)
        refetch_ok = doc.refetch_succeeded if doc is not None else False
        fetched_text = doc.text if doc is not None else ""

        # Only use live re-fetched document text when refetch succeeded; otherwise evaluate against snippet only
        evaluation_text = (
            f"{src.title}. {src.snippet}. {fetched_text}".strip()
            if refetch_ok
            else f"{src.title}. {src.snippet}".strip()
        )
        passage, grounding, semantic = extract_best_matching_passage(claim, evaluation_text)

        # Prefer sources that were successfully re-fetched over un-refetched sources
        effective_rank = grounding + (0.05 if refetch_ok else -0.10)
        if effective_rank > best_grounding:
            best_grounding = grounding
            best_semantic = semantic
            best_source = src
            best_passage = passage or src.snippet
            best_refetched = refetch_ok

    return (
        best_source,
        best_passage,
        max(0.0, best_grounding),
        best_semantic,
        best_refetched,
    )


def classify_verification_status(
    grounding_score: float,
    semantic_score: float = 0.0,
    min_grounding_score: float = 0.25,
    source_refetched: bool = True,
) -> str:
    """Classify a claim based on grounding score, semantic score, and whether re-fetch succeeded.

    A successful live re-fetch (`source_refetched=True`) is strictly required for `'verified'`.
    """
    effective_score = round((grounding_score * 0.60) + (semantic_score * 0.40), 2)
    verified_cutoff = max(0.55, min_grounding_score + 0.25)

    if effective_score >= verified_cutoff and grounding_score >= 0.50:
        # Strict requirement: cannot be 'verified' if the source could not be re-fetched!
        return "verified" if source_refetched else "partially_supported"
    if max(effective_score, grounding_score) >= min_grounding_score:
        return "partially_supported"
    return "inferred_hypothesis"


async def refetch_sources_corpus(
    sources: list[SourceCitation],
    timeout: float = 8.0,
    custom_fetcher: object | None = None,
) -> dict[str, RefetchedSourceDocument]:
    """Step 2: Re-fetch each cited source URL and track whether the live HTTP re-fetch succeeded."""
    corpus: dict[str, RefetchedSourceDocument] = {}
    if custom_fetcher is not None and callable(custom_fetcher):
        for src in sources:
            try:
                raw_res = await custom_fetcher(src.url)
                if isinstance(raw_res, tuple) and len(raw_res) == 2:
                    text_val, ok_val = str(raw_res[0]), bool(raw_res[1])
                else:
                    text_val = str(raw_res or "").strip()
                    ok_val = len(text_val) > 0
                corpus[src.url] = RefetchedSourceDocument(
                    url=src.url,
                    text=text_val,
                    refetch_succeeded=ok_val,
                    status_code=200 if ok_val else 503,
                )
            except Exception:
                corpus[src.url] = RefetchedSourceDocument(
                    url=src.url,
                    text="",
                    refetch_succeeded=False,
                    status_code=0,
                )
        return corpus

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, follow_redirects=False, timeout=timeout
    ) as client:
        for src in sources[:6]:
            if src.url in corpus:
                continue
            try:
                resp = await safe_http_get(src.url, client)
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    page_data = extract_clean_page_data(resp.text, str(resp.url), max_chars=5000)
                    headings_str = ". ".join(
                        str(h) for h in (page_data.get("headings") or [])  # type: ignore[union-attr]
                    )
                    full_text = (
                        f"{page_data.get('title', '')}. "
                        f"{page_data.get('meta_description', '')}. "
                        f"{headings_str}. "
                        f"{page_data.get('body_excerpt', '')}"
                    ).strip(". ")
                    refetch_ok = len(full_text) >= 25
                    corpus[src.url] = RefetchedSourceDocument(
                        url=src.url,
                        text=full_text,
                        refetch_succeeded=refetch_ok,
                        status_code=resp.status_code,
                    )
                else:
                    corpus[src.url] = RefetchedSourceDocument(
                        url=src.url,
                        text="",
                        refetch_succeeded=False,
                        status_code=resp.status_code,
                    )
            except Exception:
                corpus[src.url] = RefetchedSourceDocument(
                    url=src.url,
                    text="",
                    refetch_succeeded=False,
                    status_code=0,
                )

    return corpus


def annotate_statement_by_status(text: str, status: str) -> str:
    """Prefix a single statement with '[Partially Supported] ' or '[Hypothesis / Inferred] ' when needed."""
    clean = strip_status_prefixes(text)
    if status == "partially_supported":
        return f"{PARTIALLY_SUPPORTED_PREFIX}{clean}"
    if status == "inferred_hypothesis":
        return f"{HYPOTHESIS_PREFIX}{clean}"
    return clean


def _apply_unverified_policy_to_claims(
    claims_list: list[str],
    verified_records: list[VerifiedClaim],
    policy: str,
) -> list[str]:
    """Step 5: Separately label partially supported claims and mark/discard unverified claims.

    Fail-Closed Default: Any claim without a matching verification record is treated as
    `'inferred_hypothesis'` (unverified), never `'verified'`.
    """
    status_by_claim = {
        strip_status_prefixes(r.claim): r.verification_status for r in verified_records
    }
    updated: list[str] = []

    for claim_text in claims_list:
        clean_claim = strip_status_prefixes(claim_text)
        status = status_by_claim.get(clean_claim, "inferred_hypothesis")

        if status == "inferred_hypothesis":
            if policy == "discard":
                continue
            updated.append(f"{HYPOTHESIS_PREFIX}{clean_claim}")
        elif status == "partially_supported":
            updated.append(f"{PARTIALLY_SUPPORTED_PREFIX}{clean_claim}")
        else:
            updated.append(clean_claim)

    # Ensure at least one item remains so LeadReport(min_length=1) schema stays valid
    if not updated and claims_list:
        first_clean = strip_status_prefixes(claims_list[0])
        first_status = status_by_claim.get(first_clean, "inferred_hypothesis")
        updated.append(annotate_statement_by_status(first_clean, first_status))

    return updated


def _verify_single_technology(
    tech_name: str,
    report: LeadReport,
    refetched_corpus: dict[str, RefetchedSourceDocument],
    min_grounding_score: float,
) -> VerifiedClaim:
    """Verify an individual technology claim against re-fetched sources and its own runtime signal."""
    clean_tech = strip_status_prefixes(tech_name)
    tech_pattern = re.compile(rf"(?<![a-zA-Z0-9]){re.escape(clean_tech)}(?![a-zA-Z0-9])", re.I)

    # 1. Check if this specific technology is mentioned in any successfully re-fetched source document
    for src in report.sources:
        doc = refetched_corpus.get(src.url)
        if doc is not None and doc.refetch_succeeded and tech_pattern.search(doc.text):
            passage, _, _ = extract_best_matching_passage(clean_tech, doc.text)
            return VerifiedClaim(
                claim=f"Technology: {clean_tech}",
                category="tech_stack",
                source_title=src.title,
                source_url=src.url,
                source_refetched=True,
                matched_excerpt=(passage or src.snippet)[:380],
                semantic_score=0.90,
                grounding_score=0.90,
                verification_status="verified",
            )

    # 2. Check if this specific technology has its own confirmed runtime signal (HTTP header / script / DOM)
    sig_by_name = {
        strip_status_prefixes(s.name).lower(): s for s in report.tech_stack.technology_signals
    }
    own_signal = sig_by_name.get(clean_tech.lower())
    any_refetched_src = next(
        (src for src in report.sources if refetched_corpus.get(src.url, RefetchedSourceDocument("", "", False)).refetch_succeeded),
        None,
    )
    if (
        own_signal is not None
        and own_signal.detection_status == "confirmed"
        and own_signal.confidence_score >= 0.80
        and any_refetched_src is not None
    ):
        return VerifiedClaim(
            claim=f"Technology: {clean_tech}",
            category="tech_stack",
            source_title=any_refetched_src.title,
            source_url=any_refetched_src.url,
            source_refetched=True,
            matched_excerpt=f"Confirmed runtime signal: {own_signal.signal_source}"[:380],
            semantic_score=own_signal.confidence_score,
            grounding_score=own_signal.confidence_score,
            verification_status="verified",
        )

    # 3. Check if mentioned in an un-refetched source snippet (capped at partially_supported)
    for src in report.sources:
        doc = refetched_corpus.get(src.url)
        refetch_ok = doc.refetch_succeeded if doc is not None else False
        if tech_pattern.search(f"{src.title} {src.snippet}"):
            return VerifiedClaim(
                claim=f"Technology: {clean_tech}",
                category="tech_stack",
                source_title=src.title,
                source_url=src.url,
                source_refetched=refetch_ok,
                matched_excerpt=src.snippet[:380],
                semantic_score=0.60,
                grounding_score=0.60,
                verification_status="verified" if refetch_ok else "partially_supported",
            )

    # 4. Neither backed by re-fetched source text nor confirmed by its own runtime header/script signal
    primary_src = report.sources[0]
    primary_doc = refetched_corpus.get(primary_src.url)
    primary_refetched = primary_doc.refetch_succeeded if primary_doc is not None else False
    return VerifiedClaim(
        claim=f"Technology: {clean_tech}",
        category="tech_stack",
        source_title=primary_src.title,
        source_url=primary_src.url,
        source_refetched=primary_refetched,
        matched_excerpt=f"No direct evidence for '{clean_tech}' found in re-fetched source text.",
        semantic_score=0.0,
        grounding_score=0.0,
        verification_status=classify_verification_status(
            grounding_score=0.0,
            semantic_score=0.0,
            min_grounding_score=min_grounding_score,
            source_refetched=primary_refetched,
        ),
    )


async def verify_and_ground_lead_report(
    report: LeadReport,
    settings: AgentSettings = DEFAULT_SETTINGS,
    run_context: LeadRunContext | None = None,
    custom_fetcher: object | None = None,
) -> LeadReport:
    """Execute the 5-step fact verification pipeline across all core sections of LeadReport:

    - Executive Summary (`executive_summary`)
    - Recent News & Triggers (`recent_news_and_triggers`)
    - Identified Pain Points (`identified_pain_points`)
    - Tech-Stack & Infrastructure Needs (`tech_stack.inferred_infrastructure_needs` & detected technologies)
    """
    if not settings.enable_fact_checking or not report.sources:
        return report

    if run_context is not None:
        run_context.log_tool_event(
            f"Fact-Checker -> Re-fetching {len(report.sources)} cited source(s) for semantic claim verification"
        )

    # Step 2: Re-fetch the cited source documents and verify HTTP reachability
    refetched_corpus = await refetch_sources_corpus(
        report.sources,
        timeout=min(settings.http_timeout_seconds, 8.0),
        custom_fetcher=custom_fetcher,
    )

    verified_claims: list[VerifiedClaim] = []

    # Collect prose claims across Executive Summary, News Triggers, Pain Points, and Infrastructure Needs
    all_claims: list[tuple[str, str]] = []
    if report.executive_summary.strip():
        all_claims.append((report.executive_summary, "executive_summary"))
    for c in report.recent_news_and_triggers:
        all_claims.append((c, "news_trigger"))
    for p in report.identified_pain_points:
        all_claims.append((p, "pain_point"))
    if report.tech_stack.inferred_infrastructure_needs.strip():
        all_claims.append((report.tech_stack.inferred_infrastructure_needs, "tech_stack"))

    # Steps 1, 3, 4: Match each prose claim to a source, extract passage, and perform semantic + lexical comparison
    for raw_claim, category in all_claims:
        clean_claim = strip_status_prefixes(raw_claim)
        matched_src, passage, grounding_score, semantic_score, refetch_ok = (
            select_best_source_for_claim(clean_claim, report.sources, refetched_corpus)
        )
        status = classify_verification_status(
            grounding_score=grounding_score,
            semantic_score=semantic_score,
            min_grounding_score=settings.min_grounding_score,
            source_refetched=refetch_ok,
        )
        verified_claims.append(
            VerifiedClaim(
                claim=clean_claim,
                category=category,
                source_title=matched_src.title,
                source_url=matched_src.url,
                source_refetched=refetch_ok,
                matched_excerpt=passage[:380],
                semantic_score=semantic_score,
                grounding_score=grounding_score,
                verification_status=status,
            )
        )

    # Verify each detected technology individually so confirmed technologies never mask unbacked ones
    tech_status_by_name: dict[str, str] = {}
    for tech_name in report.tech_stack.detected_technologies:
        clean_tech = strip_status_prefixes(tech_name)
        tech_vc = _verify_single_technology(
            clean_tech,
            report=report,
            refetched_corpus=refetched_corpus,
            min_grounding_score=settings.min_grounding_score,
        )
        verified_claims.append(tech_vc)
        tech_status_by_name[clean_tech.lower()] = tech_vc.verification_status

    # Apply policy to individual detected_technologies and technology_signals
    updated_detected_techs: list[str] = []
    for tech_name in report.tech_stack.detected_technologies:
        clean_tech = strip_status_prefixes(tech_name)
        t_status = tech_status_by_name.get(clean_tech.lower(), "inferred_hypothesis")
        if t_status == "inferred_hypothesis":
            if settings.unverified_claim_policy == "discard":
                continue
            updated_detected_techs.append(f"{HYPOTHESIS_PREFIX}{clean_tech}")
        elif t_status == "partially_supported":
            updated_detected_techs.append(f"{PARTIALLY_SUPPORTED_PREFIX}{clean_tech}")
        else:
            updated_detected_techs.append(clean_tech)

    updated_tech_signals = []
    for sig in report.tech_stack.technology_signals:
        clean_sig_name = strip_status_prefixes(sig.name)
        t_status = tech_status_by_name.get(clean_sig_name.lower(), sig.detection_status)
        if t_status == "inferred_hypothesis":
            if settings.unverified_claim_policy == "discard":
                continue
            updated_tech_signals.append(
                sig.model_copy(
                    update={
                        "detection_status": "suspected",
                        "confidence_score": min(sig.confidence_score, 0.35),
                    }
                )
            )
        elif t_status == "partially_supported":
            updated_tech_signals.append(
                sig.model_copy(
                    update={
                        "detection_status": "suspected",
                        "confidence_score": min(sig.confidence_score, 0.65),
                    }
                )
            )
        else:
            updated_tech_signals.append(sig)

    # Step 5: Apply separate labeling for partially supported vs. unverified claims across all sections
    exec_records = [vc for vc in verified_claims if vc.category == "executive_summary"]
    updated_exec_summary = (
        annotate_statement_by_status(report.executive_summary, exec_records[0].verification_status)
        if exec_records
        else report.executive_summary
    )

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

    tech_infra_records = [
        vc
        for vc in verified_claims
        if vc.category == "tech_stack"
        and vc.claim == strip_status_prefixes(report.tech_stack.inferred_infrastructure_needs)
    ]
    updated_infra_needs = (
        annotate_statement_by_status(
            report.tech_stack.inferred_infrastructure_needs,
            tech_infra_records[0].verification_status,
        )
        if tech_infra_records
        else report.tech_stack.inferred_infrastructure_needs
    )

    if run_context is not None:
        v_count = sum(1 for vc in verified_claims if vc.verification_status == "verified")
        p_count = sum(1 for vc in verified_claims if vc.verification_status == "partially_supported")
        h_count = sum(1 for vc in verified_claims if vc.verification_status == "inferred_hypothesis")
        refetch_count = sum(1 for doc in refetched_corpus.values() if doc.refetch_succeeded)
        run_context.log_tool_event(
            f"Fact-Checker -> Sources re-fetched: {refetch_count}/{len(refetched_corpus)} | "
            f"Claims: {v_count} verified, {p_count} partially supported, {h_count} hypothesis"
        )

    return report.model_copy(
        update={
            "executive_summary": updated_exec_summary,
            "recent_news_and_triggers": updated_news,
            "identified_pain_points": updated_pains,
            "tech_stack": report.tech_stack.model_copy(
                update={
                    "detected_technologies": updated_detected_techs,
                    "technology_signals": updated_tech_signals,
                    "inferred_infrastructure_needs": updated_infra_needs,
                }
            ),
            "verified_claims": verified_claims,
        }
    )
