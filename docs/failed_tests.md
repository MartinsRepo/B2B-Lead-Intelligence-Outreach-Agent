# Failed Tests & Failure-Mode Analysis (`docs/failed_tests.md`)

## 1. Current Suite Status

- **Current Active Failures:** **`0` Failed** (`66 Passed / 66 Total`)
- All unit and integration tests currently pass locally and in CI.

This document records:
1. **Post-Mortem Analysis of the 3 Historical Test Failures** encountered during iterative development and the code fixes that resolved them.
2. **Deliberate Fail-Closed & Negative Test Cases** in the test suite that verify how the system handles malformed inputs, SSRF attacks, DNS failures, TOCTOU DNS rebinding, and unverified LLM claims.

---

## 2. Historical Test Failures & Root-Cause Resolutions

### Failure #1: `test_configurable_guardrail_settings` (`localhost:8000` Rejected When `block_private_ips=False`)

- **Test File:** [`tests/test_guardrails.py`](../tests/test_guardrails.py)
- **Failure Output Encountered During Development:**
  ```text
  FAILED tests/test_guardrails.py::test_configurable_guardrail_settings
  AssertionError: assert False is True
   + where False = ValidationOutcome(is_valid=False, normalized_target='',
     reason="'http://localhost:8000' is not a valid company domain or corporate URL.").is_valid
  ```
- **Root Cause:**
  `DOMAIN_REGEX` required a multi-label domain with a dot and TLD (`([a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,24}`), and did not permit port suffixes (`:8000`) or single-label local hostnames (`localhost`) even when `AgentSettings(block_private_ips=False)` was explicitly configured for local sandbox testing.
- **Resolution Applied in [`src/lead_agent/guardrails.py`](../src/lead_agent/guardrails.py):**
  Added optional port matching (`(?::\d{1,5})?`) to `DOMAIN_REGEX` and introduced `LOCAL_OR_IP_REGEX` so that `localhost` and IP literals are recognized as valid URL syntax, while still being strictly blocked whenever `block_private_ips=True` (the default).

---

### Failure #2: `test_verify_all_sections_and_separate_partially_supported_labels` (Partially Supported Claim Promoted to `"verified"`)

- **Test File:** [`tests/test_fact_checker.py`](../tests/test_fact_checker.py)
- **Failure Output Encountered During Development:**
  ```text
  FAILED tests/test_fact_checker.py::test_verify_all_sections_and_separate_partially_supported_labels
  AssertionError: assert False
   + where False = 'AcmeCloud announced a European banking data streaming expansion in Zurich.'.startswith('[Partially Supported] ')
  ```
- **Root Cause:**
  In `extract_best_matching_passage()`, broad semantic concept cluster matches (`CONCEPT_LAUNCH_RELEASE` + `CONCEPT_DATA_STREAMING`) combined with `high_signal_bonus` pushed the claim's `grounding_score` to `0.60` (`>= 0.55` verified cutoff) even though only 3 of the 8 meaningful tokens (`37.5%`) in the claim actually appeared in the re-fetched source passage (leaving specific claims like `"European"`, `"banking"`, and `"Zurich"` unsupported).
- **Resolution Applied in [`src/lead_agent/fact_checker.py`](../src/lead_agent/fact_checker.py):**
  Introduced a lexical coverage ceiling (`coverage_cap = lexical_recall + 0.15`; `combined_score = min(combined_score, coverage_cap)`) so that any claim where fewer than `40%–50%` of the specific terms are covered by the source passage is capped in the `"partially_supported"` range (`< 0.55`) and prefixed with `[Partially Supported] `.

---

### Failure #3: `test_simulated_toctou_dns_rebinding_prevented_by_ip_pinning` (In-Place Mutation of `response.request.url`)

- **Test File:** [`tests/test_security.py`](../tests/test_security.py)
- **Failure Output Encountered During Development:**
  ```text
  FAILED tests/test_security.py::test_simulated_toctou_dns_rebinding_prevented_by_ip_pinning
  AssertionError: assert 'toctou.example.com' == '93.184.216.34'
  ```
- **Root Cause:**
  `safe_http_get()` rightly pinned the outgoing `httpx.Request` URL to `https://93.184.216.34:8443/press?page=1` when calling `await client.send(request, follow_redirects=False)`, and then restored the logical hostname via `response.request.url = httpx.URL(current_url)` after `client.send()` returned. Because the test initially stored a reference to `request` (`observed_requests.append(request)`) and inspected `request.url.host` *after* `safe_http_get()` had already restored `response.request.url`, the post-hoc assertion saw the restored hostname instead of the wire-time pinned IP.
- **Resolution Applied in [`tests/test_security.py`](../tests/test_security.py) & [`src/lead_agent/security.py`](../src/lead_agent/security.py):**
  Updated the mock transport handler to snapshot the wire-level `request.url.host`, `port`, `headers["Host"]`, `extensions["sni_hostname"]`, and active `socket.getaddrinfo` resolution *at transport send time*, confirming that the wire connection uses `93.184.216.34` while `str(resp.url)` is cleanly restored to `https://toctou.example.com:8443/press?page=1` afterwards.

---

## 3. Summary of Deliberate Negative / Fail-Closed Tests in the Suite

To ensure high reliability in production, **35 of the 66 tests** are negative/adversarial test cases that assert the system blocks or downgrades unsafe/unverified data:

| Failure Mode Tested | Test Function(s) | Expected Fail-Closed Behavior |
| :--- | :--- | :--- |
| **Malformed / Non-Domain Input** | `test_validate_lead_input_blocks_invalid_or_local_inputs`, `test_pipeline_rejects_invalid_input_before_calling_runner` | Raises `ValueError` / triggers `@input_guardrail` tripwire before calling `Runner.run` (`0` tokens spent). |
| **Private, Loopback, Link-Local, CGNAT & Metadata IPs** | `test_is_ip_blocked_blocks_all_private_and_reserved_ranges` (18 IPs) | Blocks all private IPv4/IPv6 ranges, `127.0.0.1`, `169.254.169.254`, `100.64.0.1`, and `::ffff:169.254.169.254`. |
| **DNS Failure (`gaierror` / Timeout / Empty IPs)** | `test_fail_closed_dns_policy_blocks_unresolvable_domains_by_default` | Unconditionally blocks the URL (`is_safe=False` / raises `SSRFBlockedError`). |
| **DNS Resolving to Private / Metadata IP** | `test_dns_resolution_blocks_domain_resolving_to_private_or_metadata_ip` | Blocks domains whose DNS `A`/`AAAA` lookup returns any non-public IP. |
| **TOCTOU & Redirect DNS Rebinding** | `test_simulated_toctou_dns_rebinding_prevented_by_ip_pinning`, `test_same_domain_redirect_dns_rebinding_blocked_on_second_hop`, `test_safe_http_get_revalidates_redirect_targets_and_blocks_ssrf_redirects` | Pins validated IP at connect time (`build_ip_pinned_url_and_headers` + `pinned_dns_context`) and blocks unsafe redirect hops. |
| **SSRF Links Inside RSS Feeds & HTML** | `test_rss_and_external_source_urls_filtered_against_ssrf` | Strips internal/metadata links from RSS `<link>`, RSS `<item>`, HTML `<a>`, and rejects unsafe `SourceCitation` URLs. |
| **Failed HTTP Re-Fetch During Fact-Checking** | `test_successful_refetch_is_required_for_verified_status` | Prevents any claim from reaching `verification_status="verified"` when `source_refetched=False`. |
| **Unmapped Claims & Hallucinated Technologies** | `test_unmapped_claims_default_to_inferred_hypothesis_fail_closed`, `test_individual_technology_verification_prevents_masking_unbacked_tech` | Defaults unmapped claims and unbacked technologies to `"inferred_hypothesis"` (`[Hypothesis / Inferred]` or discarded). |
