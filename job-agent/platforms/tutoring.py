"""
Tutoring / freelance job scraper — aggregates two sources:

1. Wyzant  (https://www.wyzant.com/tutors/search)
   — HTML scrape for calculus, statistics, machine learning, Python,
     linear algebra, physics tutors.
   — job_type = "freelance", salary_text = "per-hour (negotiable)"

2. Upwork  (https://www.upwork.com/nx/jobs/search/)
   — HTML scrape of tutoring + AI + quant contract listings.
   — budget/rate extracted from job cards where available.
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

PLATFORM = "tutoring"

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

_WYZANT_URL = "https://www.wyzant.com/tutors/search"
_UPWORK_SEARCH_URL = "https://www.upwork.com/nx/jobs/search/"

# Subjects to look for on Wyzant
_WYZANT_SUBJECTS: list[str] = [
    "calculus",
    "statistics",
    "machine learning",
    "Python",
    "linear algebra",
    "physics",
]

# Upwork search queries: tutoring combined with domain keywords
_UPWORK_QUERIES: list[str] = [
    "tutoring calculus statistics",
    "tutoring machine learning Python",
    "tutoring linear algebra physics",
    "AI tutor freelance",
    "quant finance tutor",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _build_headers(accept: str = "text/html,*/*") -> dict[str, str]:
    return {
        "User-Agent": _random_ua(),
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
    }


# ---------------------------------------------------------------------------
# Internal sentinels
# ---------------------------------------------------------------------------

class _RateLimitError(Exception):
    pass


class _CaptchaError(Exception):
    pass


# ---------------------------------------------------------------------------
# Source 1 — Wyzant
# ---------------------------------------------------------------------------

def _parse_wyzant_html(html: str, subject: str) -> list[dict[str, Any]]:
    """
    Wyzant /tutors/search lists tutor *profiles*, not job postings.
    We synthesise a job-dict per tutor that surfaces tutoring opportunities
    for the given subject.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    # Tutor cards on Wyzant
    card_selectors = [
        "div[class*='tutor-result']",
        "div[class*='TutorResult']",
        "div[class*='tutor-card']",
        "article[class*='tutor']",
        "li[class*='tutor']",
        "div.listing",
    ]
    cards: list[Any] = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        container = soup.select_one(
            "div#results, ul.tutor-list, div[class*='results-list']"
        )
        if container:
            cards = container.find_all(["div", "li", "article"], recursive=False)

    for card in cards:
        try:
            # Tutor name → used as "title" (the opportunity is tutoring by this expert)
            name_el = card.select_one(
                "[class*='tutor-name'], [class*='TutorName'], h2, h3, "
                "[class*='name'], a.tutor-link"
            )
            name = name_el.get_text(strip=True) if name_el else ""
            title = f"{subject} Tutoring — {name}" if name else f"{subject} Tutor"

            # Rate / hourly
            rate_el = card.select_one(
                "[class*='rate'], [class*='Rate'], [class*='hourly'], "
                "[class*='price'], span.per-hour"
            )
            salary_text = (
                rate_el.get_text(strip=True) if rate_el else "per-hour (negotiable)"
            )
            if salary_text and "hour" not in salary_text.lower():
                salary_text = f"{salary_text}/hr"

            # Profile URL
            link_el = card.select_one("a[href]")
            url = ""
            if link_el:
                href = link_el.get("href", "")
                url = (
                    href
                    if href.startswith("http")
                    else f"https://www.wyzant.com{href}"
                )

            if not url:
                continue

            # Description: subjects list from the card
            desc_el = card.select_one(
                "[class*='subjects'], [class*='Subjects'], [class*='expertise'], "
                "[class*='bio'], p"
            )
            description = desc_el.get_text(strip=True) if desc_el else subject

            jobs.append({
                "id": make_job_id(url, title, "Wyzant"),
                "title": title,
                "company": "Wyzant",
                "url": url,
                "platform": PLATFORM,
                "description": description,
                "salary_text": salary_text,
                "job_type": "freelance",
                "discovered_at": _now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s][wyzant] Card parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_wyzant(
    session: aiohttp.ClientSession,
    limiter: Any,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for subject in _WYZANT_SUBJECTS:
        try:
            await limiter.acquire(PLATFORM)
            async with session.get(
                _WYZANT_URL,
                params={"search": subject},
                headers=_build_headers(),
                allow_redirects=True,
            ) as resp:
                if resp.status == 429:
                    raise _RateLimitError()
                if resp.status != 200:
                    logger.warning(
                        "[%s][wyzant] Status %s for subject=%r.",
                        PLATFORM, resp.status, subject,
                    )
                    continue
                html = await resp.text()
                if _captcha_detected(html):
                    raise _CaptchaError()
                batch = _parse_wyzant_html(html, subject)
                results.extend(batch)
                logger.debug(
                    "[%s][wyzant] subject=%r → %d results.", PLATFORM, subject, len(batch)
                )
        except (_RateLimitError, _CaptchaError):
            raise
        except aiohttp.ClientError as exc:
            logger.error(
                "[%s][wyzant] Network error subject=%r: %s", PLATFORM, subject, exc
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s][wyzant] Unexpected error subject=%r: %s", PLATFORM, subject, exc
            )

    return results


# ---------------------------------------------------------------------------
# Source 2 — Upwork
# ---------------------------------------------------------------------------

def _parse_upwork_html(html: str, query: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    card_selectors = [
        "article[class*='job-tile']",
        "section[class*='job-tile']",
        "div[class*='job-tile']",
        "[data-test='job-tile']",
        "div[class*='JobTile']",
        "div[class*='tile']",
    ]
    cards: list[Any] = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        container = soup.select_one(
            "div#job-results, div[class*='results'], section[class*='jobs-list']"
        )
        if container:
            cards = container.find_all(
                ["article", "section", "div"], recursive=False
            )

    for card in cards:
        try:
            # Title
            title_el = card.select_one(
                "h2, h3, [class*='title'], [class*='Title'], "
                "a[class*='job-link'], [data-test='job-title']"
            )
            title = title_el.get_text(strip=True) if title_el else ""

            if not title:
                continue

            # URL
            link_el = card.select_one("a[href]")
            url = ""
            if link_el:
                href = link_el.get("href", "")
                url = (
                    href
                    if href.startswith("http")
                    else f"https://www.upwork.com{href}"
                )

            if not url:
                continue

            # Budget / rate
            budget_el = card.select_one(
                "[data-test='budget'], [class*='budget'], [class*='Budget'], "
                "[class*='rate'], [class*='Rate'], [class*='price']"
            )
            salary_text = budget_el.get_text(strip=True) if budget_el else ""

            # Description snippet
            desc_el = card.select_one(
                "[data-test='job-description-text'], [class*='description'], "
                "[class*='snippet'], p"
            )
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Job type
            job_type_el = card.select_one(
                "[data-test='job-type'], [class*='jobType'], [class*='contract']"
            )
            job_type = job_type_el.get_text(strip=True) if job_type_el else "contract"

            jobs.append({
                "id": make_job_id(url, title, "Upwork"),
                "title": title,
                "company": "Upwork",
                "url": url,
                "platform": PLATFORM,
                "description": description,
                "salary_text": salary_text,
                "job_type": job_type,
                "discovered_at": _now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s][upwork] Card parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_upwork(
    session: aiohttp.ClientSession,
    limiter: Any,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for query in _UPWORK_QUERIES:
        try:
            await limiter.acquire(PLATFORM)
            async with session.get(
                _UPWORK_SEARCH_URL,
                params={"q": query},
                headers=_build_headers(),
                allow_redirects=True,
            ) as resp:
                if resp.status == 429:
                    raise _RateLimitError()
                if resp.status != 200:
                    logger.warning(
                        "[%s][upwork] Status %s for query=%r.",
                        PLATFORM, resp.status, query,
                    )
                    continue
                html = await resp.text()
                if _captcha_detected(html):
                    raise _CaptchaError()
                batch = _parse_upwork_html(html, query)
                results.extend(batch)
                logger.debug(
                    "[%s][upwork] query=%r → %d jobs.", PLATFORM, query, len(batch)
                )
        except (_RateLimitError, _CaptchaError):
            raise
        except aiohttp.ClientError as exc:
            logger.error(
                "[%s][upwork] Network error query=%r: %s", PLATFORM, query, exc
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s][upwork] Unexpected error query=%r: %s", PLATFORM, query, exc
            )

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scrape(preferences: dict, limiter: Any) -> list[dict]:
    """
    Scrape tutoring / freelance listings from Wyzant and Upwork.

    Parameters
    ----------
    preferences:
        Optional; keyword lists in preferences["keywords"] are not used
        directly here — subject/query lists are hard-coded for tutoring
        domains (calculus, statistics, ML, Python, linear algebra, physics).
    limiter:
        A RateLimiter with async acquire(platform) and set_pause(platform, seconds).

    Returns
    -------
    Combined list of normalised job dicts.
      - Wyzant entries: job_type="freelance", salary_text="per-hour (negotiable)"
        (or the tutor's listed rate when present).
      - Upwork entries: salary_text reflects budget/rate from the job card.
    """
    results: list[dict] = []

    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # Wyzant
        try:
            batch = await _scrape_wyzant(session, limiter)
            results.extend(batch)
        except _CaptchaError:
            logger.warning("[%s] CAPTCHA on Wyzant — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except _RateLimitError:
            logger.warning("[%s] Rate-limited on Wyzant — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Error in Wyzant scraper: %s", PLATFORM, exc)

        # Upwork
        try:
            batch = await _scrape_upwork(session, limiter)
            results.extend(batch)
        except _CaptchaError:
            logger.warning("[%s] CAPTCHA on Upwork — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except _RateLimitError:
            logger.warning("[%s] Rate-limited on Upwork — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Error in Upwork scraper: %s", PLATFORM, exc)

    logger.info("[%s] Scraped %d jobs total.", PLATFORM, len(results))
    return results
