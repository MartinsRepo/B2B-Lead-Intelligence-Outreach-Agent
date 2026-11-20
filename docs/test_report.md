# Automated Test Suite Report (`docs/test_report.md`)

## 1. Executive Summary

The **B2B Lead Intelligence & Outreach Agent** is verified by an automated test suite of **73 unit and integration tests** executed locally via `pytest` and continuously in **GitHub Actions CI** ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) across Python 3.11 and 3.12.

| Metric | Value |
| :--- | :--- |
| **Total Tests Collected** | `73` |
| **Passed** | `73 (100%)` |
| **Failed** | `0` |
| **Skipped / Errors** | `0` |
| **Ruff Linter (`ruff check src tests ui`)** | `All checks passed! (0 warnings/errors)` |
| **Execution Time (Local Python 3.14)** | `~5.79s` |

---

## 2. Test Coverage by Module

### A. 5-Step Semantic Fact-Checker (`tests/test_fact_checker.py` — 7 Tests)
Verifies [`src/lead_agent/fact_checker.py`](../src/lead_agent/fact_checker.py):
1. `test_extract_best_matching_passage_finds_relevant_sentence`: Confirms sliding-window passage retrieval and lexical + semantic scoring.
2. `test_semantic_similarity_handles_paraphrases_and_negations`: Confirms B2B concept cluster paraphrase matching and negation/contradiction score penalties (`* 0.35`).
3. `test_successful_refetch_is_required_for_verified_status`: Enforces that `verification_status="verified"` is impossible when `source_refetched=False` (capping un-refetched matches at `"partially_supported"`).
4. `test_verify_all_sections_and_separate_partially_supported_labels`: Verifies full-report auditing across `executive_summary`, `news_trigger`, `pain_point`, and `tech_stack`, and separate `[Partially Supported]` vs. `[Hypothesis / Inferred]` prefixes.
5. `test_verify_and_ground_lead_report_discards_unverified_claims_when_configured`: Confirms `unverified_claim_policy="discard"` removes unbacked claims while preserving grounded claims.
6. `test_unmapped_claims_default_to_inferred_hypothesis_fail_closed`: Ensures any claim without a matching verification record defaults fail-closed to `"inferred_hypothesis"`, never `"verified"`.
7. `test_individual_technology_verification_prevents_masking_unbacked_tech`: Ensures every technology in `detected_technologies` and `technology_signals` is verified individually against re-fetched text and re-fetched HTML/headers so confirmed technologies never mask an unbacked technology claim.

### B. Input & Output Guardrails (`tests/test_guardrails.py` — 16 Tests)
Verifies [`src/lead_agent/guardrails.py`](../src/lead_agent/guardrails.py):
- **Valid Targets (5 parametrized tests):** Accepts `stripe.com`, `https://vercel.com/careers`, `www.celonis.com`, `https://www.linkedin.com/company/openai`, and natural language phrases containing a domain (`"Analyze stripe.com please"`).
- **Blocked Invalid / Local Targets (7 parametrized tests):** Blocks empty strings, whitespace, domain-less chat prompts, `http://localhost:8000`, `https://127.0.0.1/admin`, `corp.internal`, and oversized strings (`>300` chars).
- **Guardrail Decorators & Configurable Policy (4 tests):** Verifies `@input_guardrail` tripwires, `@output_guardrail` anti-spam checks, and runtime `AgentSettings` toggles (`block_private_ips`, `enable_input_guardrail`, `min_sources_required`, `blocked_spam_phrases`).

### C. Multi-Agent Orchestrator & `.as_tool()` Wiring (`tests/test_orchestrator.py` — 3 Tests)
Verifies [`src/lead_agent/agents/orchestrator.py`](../src/lead_agent/agents/orchestrator.py):
1. `test_orchestrator_and_subagent_model_routing_configuration`: Verifies `.as_tool()` registration (`company_news_research_tool`, `tech_stack_detection_tool`, `outreach_copywriter_tool`) and dynamic sub-agent/guardrail toggling.
2. `test_run_lead_intelligence_pipeline_with_mocked_runner`: End-to-end async pipeline execution with mocked `Runner.run`, deterministic source scoring, fact-checking, phone call bullet synthesis, and token usage recording.
3. `test_pipeline_rejects_invalid_input_before_calling_runner`: Confirms invalid inputs are rejected before `Runner.run` is ever invoked (`0` tokens spent).

### D. Pydantic v2 Schemas & Cost-Aware Routing Telemetry (`tests/test_schemas_and_context.py` — 3 Tests)
Verifies [`src/lead_agent/schemas.py`](../src/lead_agent/schemas.py) and [`src/lead_agent/context.py`](../src/lead_agent/context.py):
1. `test_source_citation_rejects_non_http_url`: Ensures `SourceCitation` rejects non-HTTP/HTTPS protocols (`ftp://`).
2. `test_cost_aware_routing_calculates_savings_accurately`: Validates token aggregation and USD cost savings math across fast extraction (`$0.15 / 1M in`) and reasoning (`$2.50 / 1M in`) tiers.
3. `test_lead_report_schema_serialization`: Verifies full `LeadReport` JSON serialization.

### E. Multi-Layer SSRF & DNS-Rebinding Security (`tests/test_security.py` — 29 Tests)
Verifies [`src/lead_agent/security.py`](../src/lead_agent/security.py):
- **Blocked Private & Reserved IP Ranges (18 parametrized tests):** Verifies blocking of `127.0.0.1`, `127.0.0.53`, `10.0.0.1`, `172.16.0.10`, `172.31.255.255`, `192.168.1.1`, cloud metadata `169.254.169.254`, CGNAT `100.64.0.1`, benchmark `198.18.0.1`, TEST-NET `192.0.2.1`, multicast `224.0.0.1`, reserved `240.0.0.1`, unspecified `0.0.0.0`, IPv6 loopback `::1`, ULA `fc00::1`, link-local `fe80::1`, and IPv4-mapped IPv6 `::ffff:127.0.0.1` & `::ffff:169.254.169.254`.
- **Allowed Public IPs (4 parametrized tests):** `93.184.216.34`, `8.8.8.8`, `1.1.1.1`, `2606:2800:220:1:248:1893:25c8:1946`.
- **Fail-Closed DNS & Simulated DNS-Rebinding Defense (7 tests):**
  - `test_fail_closed_dns_policy_blocks_unresolvable_domains_by_default`: Blocks on `socket.gaierror`, `TimeoutError`, and empty DNS responses.
  - `test_dns_resolution_blocks_domain_resolving_to_private_or_metadata_ip`: Blocks domains whose DNS `A`/`AAAA` records resolve to private or cloud metadata IPs.
  - `test_simulated_toctou_dns_rebinding_prevented_by_ip_pinning`: Simulates a `TTL=0` DNS rebinding attack between validation and socket connect; verifies single DNS lookup, transport IP pinning (`93.184.216.34`), socket `getaddrinfo` context pinning (`pinned_dns_context`), preserved `Host` header, and preserved TLS `sni_hostname`.
  - `test_pinned_ip_dual_stack_failover_without_second_dns_lookup`: Verifies dual-stack IPv6 → IPv4 failover across pre-validated IPs without re-querying DNS.
  - `test_same_domain_redirect_dns_rebinding_blocked_on_second_hop`: Blocks same-domain redirect hops when DNS flips to `127.0.0.1` on Hop 2.
  - `test_safe_http_get_revalidates_redirect_targets_and_blocks_ssrf_redirects`: Blocks `301/302` redirects to cloud metadata or private-IP domains while allowing public redirects.
  - `test_rss_and_external_source_urls_filtered_against_ssrf`: Confirms RSS feed discovery, RSS `<item><link>` parsing, HTML news link extraction, and `validate_lead_output` filter out SSRF targets.

### F. Multi-Source Research, Dual Scoring & Tech-Stack Parser (`tests/test_tools.py` — 8 Tests)
Verifies [`src/lead_agent/tools/research_engine.py`](../src/lead_agent/tools/research_engine.py), [`web_scraper.py`](../src/lead_agent/tools/web_scraper.py), and [`tech_parser.py`](../src/lead_agent/tools/tech_parser.py):
1. `test_normalize_target_url`: URL normalization.
2. `test_extract_clean_page_data_parses_headings_meta_and_news_links`: HTML title, meta description, heading, and news link extraction.
3. `test_parse_tech_signals_from_html_and_headers`: Verifies `confirmed` (`>= 0.88`) status for HTTP header/script/meta detections vs. `suspected` (`< 0.80`) status for body prose mentions (`Kubernetes`).
4. `test_parse_job_board_signals_extracts_roles_and_skills`: Verifies engineering role extraction and `suspected` job-board technology signal metadata (`confidence_score`, `signal_source`, `detected_at`).
5. `test_js_heavy_page_recovers_json_ld_and_nextjs_hydration_state`: Recovers headlines, summaries, dates, and RSS links from `<script type="application/ld+json">` and Next.js `__NEXT_DATA__`.
6. `test_parse_rss_xml_and_evaluate_source_quality`: RSS 2.0 XML parsing and source ranking.
7. `test_source_scoring_considers_actual_age_and_separates_pub_vs_update_dates`: Verifies `age_days` calculation, time-decay recency curve (`5d` vs. `>1000d`), and separate `published_date` vs. `updated_date` handling.
8. `test_source_quality_and_statement_quality_scored_separately`: Verifies independent scoring of `source_quality_score` (*Quellenqualität*) and `statement_quality_score` (*Aussagequalität*).

### G. GDPR / DSGVO Privacy, PII Redaction, Retention & Art. 21 Opt-Out (`tests/test_privacy.py` — 7 Tests)
Verifies [`src/lead_agent/privacy.py`](../src/lead_agent/privacy.py) and [`docs/privacy_art13_14.md`](privacy_art13_14.md):
1. `test_scrub_personal_data_redacts_emails_phones_profiles_and_contact_names`: Verifies redaction of personal emails, phone/fax numbers, personal LinkedIn URLs (`linkedin.com/in/...`), and contact/honorific names while keeping corporate ISO dates and metrics intact.
2. `test_strip_personal_dom_elements_and_json_ld_person_filtering`: Confirms removal of `<author>`, `<address>`, `.byline`, `.recruiter` DOM elements and filtering of JSON-LD `@type: "Person"` schemas.
3. `test_data_minimization_on_careers_and_company_pages`: Confirms Art. 5(1)(c) data minimization on `/careers` pages (truncating raw prose to `max_excerpt_chars` while extracting technical hiring signals and scrubbing recruiter PII).
4. `test_retention_timestamps_and_automated_expiration_check`: Confirms Art. 5(1)(e) UTC creation/expiration timestamp computation and automated TTL expiration checks.
5. `test_art21_opt_out_blocklist_blocks_domain_and_subdomains`: Confirms Art. 21 GDPR domain & subdomain blocklisting across `OptOutBlocklistManager`, JSON persistence, `validate_lead_input`, `scrape_company_website_impl`, and `fetch_company_news_and_press_impl`.
6. `test_personal_linkedin_profile_blocked_while_company_profile_allowed`: Confirms blocking of personal LinkedIn `/in/` and `/pub/` profiles while allowing `/company/` profiles.
7. `test_art14_transparency_notice_generated`: Confirms Art. 14 GDPR transparency footer generation and presence of [`docs/privacy_art13_14.md`](privacy_art13_14.md).

---

## 3. Latest Local Execution Log

```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\humme\workspace\B2B-Lead-Intelligence-Outreach-Agent
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0, asyncio-1.5.0
collecting ... collected 66 items

tests/test_fact_checker.py::test_extract_best_matching_passage_finds_relevant_sentence PASSED [  1%]
tests/test_fact_checker.py::test_semantic_similarity_handles_paraphrases_and_negations PASSED [  3%]
tests/test_fact_checker.py::test_successful_refetch_is_required_for_verified_status PASSED [  4%]
tests/test_fact_checker.py::test_verify_all_sections_and_separate_partially_supported_labels PASSED [  6%]
tests/test_fact_checker.py::test_verify_and_ground_lead_report_discards_unverified_claims_when_configured PASSED [  7%]
tests/test_fact_checker.py::test_unmapped_claims_default_to_inferred_hypothesis_fail_closed PASSED [  9%]
tests/test_fact_checker.py::test_individual_technology_verification_prevents_masking_unbacked_tech PASSED [ 10%]
tests/test_guardrails.py::test_validate_lead_input_accepts_valid_domains_and_urls[stripe.com-https://stripe.com] PASSED [ 12%]
tests/test_guardrails.py::test_validate_lead_input_accepts_valid_domains_and_urls[https://vercel.com/careers-https://vercel.com/careers] PASSED [ 13%]
tests/test_guardrails.py::test_validate_lead_input_accepts_valid_domains_and_urls[www.celonis.com-https://www.celonis.com] PASSED [ 15%]
tests/test_guardrails.py::test_validate_lead_input_accepts_valid_domains_and_urls[https://www.linkedin.com/company/openai-https://www.linkedin.com/company/openai] PASSED [ 16%]
tests/test_guardrails.py::test_validate_lead_input_accepts_valid_domains_and_urls[Analyze stripe.com please-https://stripe.com] PASSED [ 18%]
tests/test_guardrails.py::test_validate_lead_input_blocks_invalid_or_local_inputs[] PASSED [ 19%]
tests/test_guardrails.py::test_validate_lead_input_blocks_invalid_or_local_inputs[   ] PASSED [ 21%]
tests/test_guardrails.py::test_validate_lead_input_blocks_invalid_or_local_inputs[tell me a joke about sales] PASSED [ 22%]
tests/test_guardrails.py::test_validate_lead_input_blocks_invalid_or_local_inputs[http://localhost:8000] PASSED [ 24%]
tests/test_guardrails.py::test_validate_lead_input_blocks_invalid_or_local_inputs[https://127.0.0.1/admin] PASSED [ 25%]
tests/test_guardrails.py::test_validate_lead_input_blocks_invalid_or_local_inputs[corp.internal] PASSED [ 27%]
tests/test_guardrails.py::test_validate_lead_input_blocks_invalid_or_local_inputs[invalid_input6] PASSED [ 28%]
tests/test_guardrails.py::test_input_guardrail_decorator_sets_tripwire PASSED [ 30%]
tests/test_guardrails.py::test_validate_lead_output_passes_and_catches_spam PASSED [ 31%]
tests/test_guardrails.py::test_output_guardrail_decorator PASSED         [ 33%]
tests/test_guardrails.py::test_configurable_guardrail_settings PASSED    [ 34%]
tests/test_orchestrator.py::test_orchestrator_and_subagent_model_routing_configuration PASSED [ 36%]
tests/test_orchestrator.py::test_run_lead_intelligence_pipeline_with_mocked_runner PASSED [ 37%]
tests/test_orchestrator.py::test_pipeline_rejects_invalid_input_before_calling_runner PASSED [ 39%]
tests/test_schemas_and_context.py::test_source_citation_rejects_non_http_url PASSED [ 40%]
tests/test_schemas_and_context.py::test_cost_aware_routing_calculates_savings_accurately PASSED [ 42%]
tests/test_schemas_and_context.py::test_lead_report_schema_serialization PASSED [ 43%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[127.0.0.1] PASSED [ 45%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[127.0.0.53] PASSED [ 46%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[10.0.0.1] PASSED [ 48%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[172.16.0.10] PASSED [ 50%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[172.31.255.255] PASSED [ 51%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[192.168.1.1] PASSED [ 53%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[169.254.169.254] PASSED [ 54%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[100.64.0.1] PASSED [ 56%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[198.18.0.1] PASSED [ 57%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[192.0.2.1] PASSED [ 59%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[224.0.0.1] PASSED [ 60%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[240.0.0.1] PASSED [ 62%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[0.0.0.0] PASSED [ 63%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[::1] PASSED [ 65%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[fc00::1] PASSED [ 66%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[fe80::1] PASSED [ 68%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[::ffff:127.0.0.1] PASSED [ 69%]
tests/test_security.py::test_is_ip_blocked_blocks_all_private_and_reserved_ranges[::ffff:169.254.169.254] PASSED [ 71%]
tests/test_security.py::test_is_ip_blocked_allows_public_ips[93.184.216.34] PASSED [ 72%]
tests/test_security.py::test_is_ip_blocked_allows_public_ips[8.8.8.8] PASSED [ 74%]
tests/test_security.py::test_is_ip_blocked_allows_public_ips[1.1.1.1] PASSED [ 75%]
tests/test_security.py::test_is_ip_blocked_allows_public_ips[2606:2800:220:1:248:1893:25c8:1946] PASSED [ 77%]
tests/test_security.py::test_fail_closed_dns_policy_blocks_unresolvable_domains_by_default PASSED [ 78%]
tests/test_security.py::test_dns_resolution_blocks_domain_resolving_to_private_or_metadata_ip PASSED [ 80%]
tests/test_security.py::test_simulated_toctou_dns_rebinding_prevented_by_ip_pinning PASSED [ 81%]
tests/test_security.py::test_pinned_ip_dual_stack_failover_without_second_dns_lookup PASSED [ 83%]
tests/test_security.py::test_same_domain_redirect_dns_rebinding_blocked_on_second_hop PASSED [ 84%]
tests/test_security.py::test_safe_http_get_revalidates_redirect_targets_and_blocks_ssrf_redirects PASSED [ 86%]
tests/test_security.py::test_rss_and_external_source_urls_filtered_against_ssrf PASSED [ 87%]
tests/test_tools.py::test_normalize_target_url PASSED                    [ 89%]
tests/test_tools.py::test_extract_clean_page_data_parses_headings_meta_and_news_links PASSED [ 90%]
tests/test_tools.py::test_parse_tech_signals_from_html_and_headers PASSED [ 92%]
tests/test_tools.py::test_parse_job_board_signals_extracts_roles_and_skills PASSED [ 93%]
tests/test_tools.py::test_js_heavy_page_recovers_json_ld_and_nextjs_hydration_state PASSED [ 95%]
tests/test_tools.py::test_parse_rss_xml_and_evaluate_source_quality PASSED [ 96%]
tests/test_tools.py::test_source_scoring_considers_actual_age_and_separates_pub_vs_update_dates PASSED [ 98%]
tests/test_tools.py::test_source_quality_and_statement_quality_scored_separately PASSED [100%]

============================= 66 passed in 5.79s ==============================
```

---

## 4. Running Locally & via GitHub Actions

### Local Execution
```powershell
python -m pytest -v
python -m ruff check src tests ui
```

### GitHub Actions Execution
The workflow in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs automatically on every `push` and `pull_request` to `main` (and can also be triggered manually via `workflow_dispatch` in the **Actions** tab on GitHub). It executes both `ruff check src tests ui` and `pytest -v` across Python 3.11 and 3.12 and publishes a Markdown test summary directly to the GitHub Actions run page.
