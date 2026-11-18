"""Scraping and HTML parsing tools for the B2B Lead Intelligence Agent."""

from lead_agent.tools.tech_parser import (
    detect_website_tech_stack,
    detect_website_tech_stack_impl,
    parse_job_board_signals,
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
    "detect_website_tech_stack",
    "detect_website_tech_stack_impl",
    "extract_clean_page_data",
    "fetch_company_news_and_press",
    "fetch_company_news_and_press_impl",
    "normalize_target_url",
    "parse_job_board_signals",
    "parse_tech_signals_from_html",
    "scrape_careers_and_job_postings",
    "scrape_careers_and_job_postings_impl",
    "scrape_company_website",
    "scrape_company_website_impl",
]

