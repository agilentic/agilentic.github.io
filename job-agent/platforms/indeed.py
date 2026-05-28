"""
Indeed job scraper — HTML scrape of the public job search results.
Paginates with the `start` parameter up to 200 results per keyword.
"""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime, timezone
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PLATFORM = "indeed"

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

_SEARCH_URL = "https://www.indeed.com/jobs"
_PAGE_SIZE = 15   # Indeed returns ~15 results per page
_MAX_RESULTS = 200


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
        "Referer": "https://www.indeed.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1",
    }


def _extract_job_url(card: BeautifulSoup) -> str:
    """Build an absolute URL from a result card."""
    # Modern layout: data-jk attribute on the card itself
    jk = card.get("data-jk") or card.get("id", "").replace("job_", "")
    if jk:
        return f"https://www.indeed.com/viewjob?jk={jk}"

    # Title link
    title_link = card.select_one("h2.jobTitle a, .jobTitle a, a[data-jk]")
    if title_link:
        href = title_link.get("href", "")
        data_jk = title_link.get("data-jk", "")
        if data_jk:
            return f"https://www.indeed.com/viewjob?jk={data_jk}"
        if href.startswith("/rc/clk") or href.startswith("/pagead"):
            return f"https://www.indeed.com{href}"
        if href.startswith("http"):
            return href

    return ""


def _parse_card(card: BeautifulSoup) -> dict[str, Any] | None:
    """Parse a single Indeed result card."""
    try:
        # Title
        title_el = card.select_one(
            "h2.jobTitle span[title], h2.jobTitle span, .jobTitle span[title], "
            "[data-testid='jobsearch-JobInfoHeader-title'], h2 a span"
        )
        title = ""
        if title_el:
            title = title_el.get("title") or title_el.get_text(strip=True)
        if not title:
            h2 = card.find("h2")
            if h2:
                title = h2.get_text(strip=True)

        # Company
        company_el = card.select_one(
            ".companyName, [data-testid='company-name'], "
            "span.companyName, .css-1h7lukg"
        )
        company = company_el.get_text(strip=True) if company_el else ""

        # URL
        url = _extract_job_url(card)

        if not title or not url:
            return None

        # Salary
        salary_el = card.select_one(
            ".salary-snippet, .salary-snippet-container, "
            "[data-testid='attribute_snippet_testid'], "
            ".css-1cvvo1h, [class*='salary']"
        )
        salary_text = salary_el.get_text(strip=True) if salary_el else ""

        # Description snippet
        desc_el = card.select_one(
            ".job-snippet, .summary, [class*='snippet'], "
            "[data-testid='jobsearch-SerpJobCard-snippet']"
        )
        description = desc_el.get_text(strip=True) if desc_el else ""

        # Job type (Remote / Full-time etc.)
        job_type_el = card.select_one(
            ".remote-tag, .attribute_snippet, [class*='workType'], "
            "[class*='jobType'], .metadata.remote"
        )
        job_type = job_type_el.get_text(strip=True) if job_type_el else ""

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
    """Parse a full Indeed search results page."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    # Primary: the mosaic job cards list
    result_list = soup.select_one(
        "#mosaic-jobResults ul, "
        ".jobsearch-ResultsList, "
        "#resultsCol ul, "
        "[data-testid='jobsearch-ResultsList']"
    )

    if result_list:
        cards = result_list.find_all("li", recursive=False)
    else:
        # Fallback: any li with a data-jk or class hinting at a job card
        cards = soup.select(
            "div.job_seen_beacon, "
            "li.css-5lfssm, "
            "td.resultContent, "
            "div[data-jk], "
            "li[data-jk]"
        )

    for card in cards:
        job = _parse_card(card)
        if job:
            jobs.append(job)

    return jobs


async def scrape(preferences: dict, limiter: Any) -> list[dict]:
    """
    Scrape Indeed job search for each keyword set in preferences.

    Parameters
    ----------
    preferences:
        Must contain at minimum:
          - preferences["keywords"]: dict[str, list[str]]
          - preferences.get("location", "")  — empty means remote/nationwide
    limiter:
        A RateLimiter with async acquire(platform) and set_pause(platform, seconds).
    """
    results: list[dict] = []
    location: str = preferences.get("location", "")

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
            start = 0
            while start < _MAX_RESULTS:
                params: dict[str, Any] = {
                    "q": keyword,
                    "remotejobs": "1",
                    "start": start,
                }
                if location:
                    params["l"] = location

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
                                "[%s] Status %s for keyword=%r start=%d.",
                                PLATFORM, resp.status, keyword, start,
                            )
                            break

                        html = await resp.text()

                        if _captcha_detected(html):
                            logger.warning(
                                "[%s] CAPTCHA detected — pausing 7200 s.", PLATFORM
                            )
                            limiter.set_pause(PLATFORM, 7200)
                            return results

                        page_jobs = _parse_page(html)
                        if not page_jobs:
                            break  # no more results

                        results.extend(page_jobs)
                        logger.debug(
                            "[%s] keyword=%r start=%d → %d jobs.",
                            PLATFORM, keyword, start, len(page_jobs),
                        )

                        if len(page_jobs) < _PAGE_SIZE:
                            break  # last page

                        start += _PAGE_SIZE

                except aiohttp.ClientError as exc:
                    logger.error(
                        "[%s] Network error keyword=%r start=%d: %s",
                        PLATFORM, keyword, start, exc,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "[%s] Unexpected error keyword=%r start=%d: %s",
                        PLATFORM, keyword, start, exc,
                    )
                    break

    logger.info("[%s] Scraped %d jobs.", PLATFORM, len(results))
    return results
