"""Scraping, multi-source research, and HTML parsing tools for the B2B Lead Intelligence Agent."""

from lead_agent.tools.research_engine import (
    EvaluatedSource,
    deduplicate_and_rank_sources,
    discover_rss_feed_urls,
    evaluate_source_quality,
    extract_json_ld_and_hydration_state,
    parse_rss_or_atom_xml,
)
from lead_agent.tools.tech_parser import (
    classify_tech_status,
    detect_website_tech_stack,
    detect_website_tech_stack_impl,
    parse_job_board_signals,
    parse_tech_signals_detailed,
    parse_tech_signals_from_html,
    scrape_careers_and_job_postings,
    scrape_careers_and_job_postings_impl,
)
from lead_agent.tools.web_scraper import (
    extract_clean_page_data,
    fetch_company_news_and_press,
    fetch_company_news_and_press_impl,
    normalize_target_url,
    scrape_company_website,
    scrape_company_website_impl,
)

__all__ = [
    "EvaluatedSource",
    "classify_tech_status",
    "deduplicate_and_rank_sources",
    "detect_website_tech_stack",
    "detect_website_tech_stack_impl",
    "discover_rss_feed_urls",
    "evaluate_source_quality",
    "extract_clean_page_data",
    "extract_json_ld_and_hydration_state",
    "fetch_company_news_and_press",
    "fetch_company_news_and_press_impl",
    "normalize_target_url",
    "parse_job_board_signals",
    "parse_rss_or_atom_xml",
    "parse_tech_signals_detailed",
    "parse_tech_signals_from_html",
    "scrape_careers_and_job_postings",
    "scrape_careers_and_job_postings_impl",
    "scrape_company_website",
    "scrape_company_website_impl",
]
