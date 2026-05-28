"""
Glassdoor job scraper — HTML scrape of the public jobs search page.
"""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PLATFORM = "glassdoor"

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

_SEARCH_URL = "https://www.glassdoor.com/Job/jobs.htm"


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def make_job_id(url: str, title: str, company: str) -> str:
    return hashlib.sha256(f"{url}{title}{company}".encode()).hexdigest()


def _captcha_detected(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in ("captcha", "robot", "verify you are human")
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_headers() -> dict[str, str]:
    return {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.glassdoor.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }


def _extract_salary(card: BeautifulSoup) -> str:
    """Try multiple CSS selectors / text patterns to find salary text."""
    # Primary selectors used on recent Glassdoor layouts
    selectors = [
        ".salary-estimate",
        "[data-test='detailSalary']",
        "[data-test='salaryEstimate']",
        ".css-1xe2xww",           # observed class in 2024 layout
        ".css-1bluz6i",
        "[class*='salary']",
        "[class*='Salary']",
    ]
    for sel in selectors:
        el = card.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return ""


def _extract_job_type(card: BeautifulSoup) -> str:
    selectors = [
        "[data-test='job-type']",
        ".job-type",
        "[class*='jobType']",
        "[class*='WorkType']",
    ]
    for sel in selectors:
        el = card.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return ""


def _parse_card(card: BeautifulSoup) -> dict[str, Any] | None:
    """Parse a single Glassdoor job-listing card."""
    try:
        # Title
        title_el = card.select_one(
            "[data-test='job-title'], .job-title, [class*='jobTitle'], a[data-test='job-link']"
        )
        title = title_el.get_text(strip=True) if title_el else ""

        # Company
        company_el = card.select_one(
            "[data-test='employer-name'], .employer-name, [class*='companyName'], [class*='EmployerName']"
        )
        company = company_el.get_text(strip=True) if company_el else ""

        # URL — prefer explicit link elements
        url = ""
        link_el = card.select_one(
            "a[data-test='job-link'], a[class*='jobLink'], a[class*='JobLink'], a.job-title"
        )
        if link_el and link_el.get("href"):
            href = link_el["href"]
            if href.startswith("http"):
                url = href
            else:
                url = f"https://www.glassdoor.com{href}"
        elif not url:
            # Fallback: first anchor with a plausible job URL
            for a in card.find_all("a", href=True):
                href = a["href"]
                if "/job-listing/" in href or "/Job/" in href:
                    url = href if href.startswith("http") else f"https://www.glassdoor.com{href}"
                    break

        if not title or not url:
            return None

        salary_text = _extract_salary(card)
        job_type = _extract_job_type(card)

        # Description snippet
        desc_el = card.select_one(
            "[data-test='job-description'], .job-snippet, [class*='description'], [class*='Description']"
        )
        description = desc_el.get_text(strip=True) if desc_el else ""

        return {
            "id": make_job_id(url, title, company),
            "title": title,
            "company": company,
            "url": url,
            "platform": PLATFORM,
            "description": description,
            "salary_text": salary_text,
            "job_type": job_type,
            "discovered_at": _now_iso(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("[%s] Error parsing card: %s", PLATFORM, exc)
        return None


def _parse_page(html: str) -> list[dict[str, Any]]:
    """Parse a full Glassdoor search results page."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    # Try multiple container selectors used across layout versions
    card_selectors = [
        "li.react-job-listing",
        "li[data-id]",
        "div[data-id]",
        "[data-test='jobListing']",
        "li.jl",
        ".JobCard_jobCardContainer__arQqu",   # 2024 class
        "[class*='jobCard']",
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        # Last resort: all <li> children of the job list
        container = soup.select_one("ul#MainCol, ul.jobs-list, [data-test='jobsList']")
        if container:
            cards = container.find_all("li", recursive=False)

    for card in cards:
        job = _parse_card(card)
        if job:
            jobs.append(job)

    return jobs


async def scrape(preferences: dict, limiter: Any) -> list[dict]:
    """
    Scrape Glassdoor job search for each keyword set in preferences.

    Parameters
    ----------
    preferences:
        Must contain at minimum:
          - preferences["keywords"]: dict[str, list[str]]
          - preferences.get("location", "United States")
    limiter:
        A RateLimiter with async acquire(platform) and set_pause(platform, seconds).
    """
    results: list[dict] = []
    location: str = preferences.get("location", "United States")

    keywords_map: dict[str, list[str]] = preferences.get("keywords", {})
    all_keywords: list[str] = []
    seen_kw: set[str] = set()
    for kw_list in keywords_map.values():
        for kw in kw_list:
            if kw not in seen_kw:
                all_keywords.append(kw)
                seen_kw.add(kw)

    if not all_keywords:
        logger.warning("[%s] No keywords found in preferences.", PLATFORM)
        return results

    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(
        timeout=timeout, connector=connector
    ) as session:
        for keyword in all_keywords:
            params: dict[str, str] = {
                "sc.keyword": keyword,
                "locT": "N",
                "locId": "1",
                "jobType": "",
                "fromAge": "7",
                "minSalary": "0",
                "includeNoSalaryJobs": "true",
                "radius": "100",
                "cityId": "-1",
                "minRating": "0.0",
                "industryId": "-1",
                "sgocId": "-1",
                "seniorityType": "all",
                "applicationType": "0",
                "remoteWorkType": "1",
                "keyword": keyword,
                "l": location,
            }

            try:
                await limiter.acquire(PLATFORM)
                async with session.get(
                    _SEARCH_URL,
                    params=params,
                    headers=_build_headers(),
                    allow_redirects=True,
                ) as resp:
                    if resp.status == 429:
                        logger.warning(
                            "[%s] 429 Too Many Requests — pausing 7200 s.", PLATFORM
                        )
                        limiter.set_pause(PLATFORM, 7200)
                        return results

                    if resp.status != 200:
                        logger.warning(
                            "[%s] Status %s for keyword=%r.", PLATFORM, resp.status, keyword
                        )
                        continue

                    html = await resp.text()

                    if _captcha_detected(html):
                        logger.warning(
                            "[%s] CAPTCHA detected — pausing 7200 s.", PLATFORM
                        )
                        limiter.set_pause(PLATFORM, 7200)
                        return results

                    page_jobs = _parse_page(html)
                    results.extend(page_jobs)
                    logger.debug(
                        "[%s] keyword=%r → %d jobs found.", PLATFORM, keyword, len(page_jobs)
                    )

            except aiohttp.ClientError as exc:
                logger.error(
                    "[%s] Network error for keyword=%r: %s", PLATFORM, keyword, exc
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[%s] Unexpected error for keyword=%r: %s", PLATFORM, keyword, exc
                )

    logger.info("[%s] Scraped %d jobs.", PLATFORM, len(results))
    return results
