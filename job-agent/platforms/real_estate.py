"""
Real-estate job board scraper — aggregates two specialised sources:

1. SelectLeaders  (https://www.selectleaders.com/jobs/)
   — HTML scrape for REPE / CRE roles
2. BISNOW jobs    (https://www.bisnow.com/jobs)
   — HTML scrape using real_estate keywords

Results are filtered against preferences["keywords"]["real_estate"].
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

PLATFORM = "real_estate"

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

_SELECTLEADERS_URL = "https://www.selectleaders.com/jobs/"
_BISNOW_SEARCH_URL = "https://www.bisnow.com/jobs"

_DEFAULT_RE_KEYWORDS: list[str] = [
    "real estate private equity",
    "REPE analyst",
    "CRE analyst",
    "commercial real estate",
    "acquisitions analyst",
    "asset management real estate",
    "real estate investment",
    "property analyst",
    "real estate finance",
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


def _keyword_match(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


# ---------------------------------------------------------------------------
# Internal sentinels
# ---------------------------------------------------------------------------

class _RateLimitError(Exception):
    pass


class _CaptchaError(Exception):
    pass


# ---------------------------------------------------------------------------
# Source 1 — SelectLeaders
# ---------------------------------------------------------------------------

def _parse_selectleaders_html(html: str, keywords: list[str]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    card_selectors = [
        "div.job-listing",
        "li.job-listing",
        "article.job",
        "div[class*='job-item']",
        "tr.job-row",
        "[class*='jobCard']",
    ]
    cards: list[Any] = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        container = soup.select_one(
            "table#job-listings, ul.jobs-list, div#job-results, div.jobs"
        )
        if container:
            cards = container.find_all(
                ["tr", "li", "div", "article"], recursive=False
            )

    for card in cards:
        try:
            title_el = card.select_one(
                "h2 a, h3 a, .job-title a, td.title a, [class*='title'] a, "
                "a[class*='job-link']"
            )
            if not title_el:
                title_el = card.select_one("h2, h3, .job-title, td.title")
            title = title_el.get_text(strip=True) if title_el else ""

            company_el = card.select_one(
                ".company, .employer, [class*='company'], [class*='employer'], "
                "td.company, td.employer"
            )
            company = company_el.get_text(strip=True) if company_el else ""

            link_el = card.select_one("a[href]")
            url = ""
            if link_el:
                href = link_el.get("href", "")
                url = (
                    href
                    if href.startswith("http")
                    else f"https://www.selectleaders.com{href}"
                )

            if not title or not url:
                continue

            combined = f"{title} {company}"
            if keywords and not _keyword_match(combined, keywords):
                continue

            salary_el = card.select_one(
                ".salary, [class*='salary'], td.salary, [class*='compensation']"
            )
            salary_text = salary_el.get_text(strip=True) if salary_el else ""

            desc_el = card.select_one(
                ".description, .summary, [class*='description'], td.description"
            )
            description = desc_el.get_text(strip=True) if desc_el else ""

            job_type_el = card.select_one(
                ".job-type, [class*='jobType'], td.type"
            )
            job_type = job_type_el.get_text(strip=True) if job_type_el else ""

            jobs.append({
                "id": make_job_id(url, title, company),
                "title": title,
                "company": company,
                "url": url,
                "platform": PLATFORM,
                "description": description,
                "salary_text": salary_text,
                "job_type": job_type,
                "discovered_at": _now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s][selectleaders] Card parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_selectleaders(
    session: aiohttp.ClientSession,
    limiter: Any,
    keywords: list[str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        await limiter.acquire(PLATFORM)
        async with session.get(
            _SELECTLEADERS_URL,
            headers=_build_headers(),
            allow_redirects=True,
        ) as resp:
            if resp.status == 429:
                raise _RateLimitError()
            if resp.status != 200:
                logger.warning("[%s][selectleaders] Status %s.", PLATFORM, resp.status)
                return results
            html = await resp.text()
            if _captcha_detected(html):
                raise _CaptchaError()
            results = _parse_selectleaders_html(html, keywords)
            logger.debug(
                "[%s][selectleaders] %d jobs parsed.", PLATFORM, len(results)
            )
    except (_RateLimitError, _CaptchaError):
        raise
    except aiohttp.ClientError as exc:
        logger.error("[%s][selectleaders] Network error: %s", PLATFORM, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s][selectleaders] Unexpected error: %s", PLATFORM, exc)
    return results


# ---------------------------------------------------------------------------
# Source 2 — BISNOW jobs
# ---------------------------------------------------------------------------

def _parse_bisnow_html(html: str, keywords: list[str]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    card_selectors = [
        "div[class*='job-card']",
        "div[class*='JobCard']",
        "article[class*='job']",
        "li[class*='job']",
        "div[class*='listing']",
        "[data-job-id]",
    ]
    cards: list[Any] = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        container = soup.select_one(
            "div#jobs-list, div.jobs-container, ul.job-listings"
        )
        if container:
            cards = container.find_all(
                ["div", "li", "article"], recursive=False
            )

    for card in cards:
        try:
            title_el = card.select_one(
                "h2 a, h3 a, [class*='title'] a, [class*='Title'] a, a.job-title"
            )
            if not title_el:
                title_el = card.select_one(
                    "h2, h3, [class*='title'], [class*='Title']"
                )
            title = title_el.get_text(strip=True) if title_el else ""

            company_el = card.select_one(
                "[class*='company'], [class*='Company'], [class*='employer'], "
                "[class*='org'], span.company"
            )
            company = company_el.get_text(strip=True) if company_el else ""

            link_el = card.select_one("a[href]")
            url = ""
            if link_el:
                href = link_el.get("href", "")
                url = (
                    href
                    if href.startswith("http")
                    else f"https://www.bisnow.com{href}"
                )

            if not title or not url:
                continue

            combined = f"{title} {company}"
            if keywords and not _keyword_match(combined, keywords):
                continue

            salary_el = card.select_one(
                "[class*='salary'], [class*='Salary'], [class*='pay']"
            )
            salary_text = salary_el.get_text(strip=True) if salary_el else ""

            desc_el = card.select_one(
                "[class*='description'], [class*='snippet'], [class*='summary']"
            )
            description = desc_el.get_text(strip=True) if desc_el else ""

            job_type_el = card.select_one(
                "[class*='type'], [class*='jobType'], [class*='workType']"
            )
            job_type = job_type_el.get_text(strip=True) if job_type_el else ""

            jobs.append({
                "id": make_job_id(url, title, company),
                "title": title,
                "company": company,
                "url": url,
                "platform": PLATFORM,
                "description": description,
                "salary_text": salary_text,
                "job_type": job_type,
                "discovered_at": _now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s][bisnow] Card parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_bisnow(
    session: aiohttp.ClientSession,
    limiter: Any,
    keywords: list[str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for keyword in keywords:
        try:
            await limiter.acquire(PLATFORM)
            async with session.get(
                _BISNOW_SEARCH_URL,
                params={"q": keyword},
                headers=_build_headers(),
                allow_redirects=True,
            ) as resp:
                if resp.status == 429:
                    raise _RateLimitError()
                if resp.status != 200:
                    logger.warning(
                        "[%s][bisnow] Status %s for keyword=%r.",
                        PLATFORM, resp.status, keyword,
                    )
                    continue
                html = await resp.text()
                if _captcha_detected(html):
                    raise _CaptchaError()
                batch = _parse_bisnow_html(html, keywords)
                results.extend(batch)
                logger.debug(
                    "[%s][bisnow] keyword=%r → %d jobs.", PLATFORM, keyword, len(batch)
                )
        except (_RateLimitError, _CaptchaError):
            raise
        except aiohttp.ClientError as exc:
            logger.error(
                "[%s][bisnow] Network error keyword=%r: %s", PLATFORM, keyword, exc
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s][bisnow] Unexpected error keyword=%r: %s", PLATFORM, keyword, exc
            )

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scrape(preferences: dict, limiter: Any) -> list[dict]:
    """
    Scrape real-estate job boards (SelectLeaders + BISNOW).

    Parameters
    ----------
    preferences:
        Expected keys:
          - preferences["keywords"]["real_estate"]: list[str]
    limiter:
        A RateLimiter with async acquire(platform) and set_pause(platform, seconds).

    Returns
    -------
    Combined list of normalised job dicts.
    """
    results: list[dict] = []
    keywords_map: dict[str, list[str]] = preferences.get("keywords", {})
    re_keywords: list[str] = keywords_map.get("real_estate", _DEFAULT_RE_KEYWORDS)

    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # SelectLeaders
        try:
            batch = await _scrape_selectleaders(session, limiter, re_keywords)
            results.extend(batch)
        except _CaptchaError:
            logger.warning("[%s] CAPTCHA on SelectLeaders — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except _RateLimitError:
            logger.warning("[%s] Rate-limited on SelectLeaders — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Error in SelectLeaders scraper: %s", PLATFORM, exc)

        # BISNOW
        try:
            batch = await _scrape_bisnow(session, limiter, re_keywords)
            results.extend(batch)
        except _CaptchaError:
            logger.warning("[%s] CAPTCHA on BISNOW — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except _RateLimitError:
            logger.warning("[%s] Rate-limited on BISNOW — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Error in BISNOW scraper: %s", PLATFORM, exc)

    logger.info("[%s] Scraped %d jobs total.", PLATFORM, len(results))
    return results
