"""
Niche finance job board scraper — aggregates two specialised sources:

1. eFinancialCareers  (https://www.efinancialcareers.com/search)
   — HTML scrape, uses preferences["keywords"]["quant"]
2. Braintrust          (https://app.usebraintrust.com/jobs/)
   — HTML scrape, filtered to quant / finance / AI roles
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

PLATFORM = "niche_finance"

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

_EFC_BASE_URL = "https://www.efinancialcareers.com/search"
_BRAINTRUST_URL = "https://app.usebraintrust.com/jobs/"

# Default quant keywords used when preferences["keywords"]["quant"] is absent
_DEFAULT_QUANT_KEYWORDS: list[str] = [
    "quantitative analyst",
    "quant researcher",
    "quant developer",
    "algorithmic trading",
    "risk analyst",
    "derivatives",
    "financial engineer",
    "ML finance",
    "AI finance",
]

# Braintrust role filter terms
_BRAINTRUST_FILTER_TERMS: list[str] = [
    "quant", "finance", "ai", "machine learning", "data science",
    "algo", "trading", "risk", "financial engineer",
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
# Source 1 — eFinancialCareers
# ---------------------------------------------------------------------------

def _parse_efc_html(html: str, keyword: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    # eFinancialCareers uses various card layouts; try in preference order.
    card_selectors = [
        "article.job-result",
        "div.job-result",
        "li.job-listing",
        "[data-job-id]",
        "[class*='jobCard']",
        "[class*='job-card']",
        "div.result",
    ]
    cards: list[Any] = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        container = soup.select_one("ul.jobs-list, div#search-results, div.jobs")
        if container:
            cards = container.find_all(["li", "div", "article"], recursive=False)

    for card in cards:
        try:
            # Title
            title_el = card.select_one(
                "h2 a, h3 a, .job-title a, a.job-link, [class*='jobTitle'] a, "
                "[class*='title'] a, a[data-job-id]"
            )
            if not title_el:
                title_el = card.select_one("h2, h3, .job-title, [class*='title']")
            title = title_el.get_text(strip=True) if title_el else ""

            # Company
            company_el = card.select_one(
                ".company-name, .employer, [class*='company'], [class*='employer']"
            )
            company = company_el.get_text(strip=True) if company_el else ""

            # URL
            link_el = card.select_one("a[href]")
            url = ""
            if link_el:
                href = link_el.get("href", "")
                url = (
                    href
                    if href.startswith("http")
                    else f"https://www.efinancialcareers.com{href}"
                )

            if not title or not url:
                continue

            # Salary
            salary_el = card.select_one(
                ".salary, [class*='salary'], [class*='Salary'], "
                ".compensation, [class*='compensation']"
            )
            salary_text = salary_el.get_text(strip=True) if salary_el else ""

            # Description snippet
            desc_el = card.select_one(
                ".job-description, .description, [class*='description'], .snippet, .summary"
            )
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Job type
            job_type_el = card.select_one(
                ".job-type, [class*='jobType'], [class*='workType'], .type"
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
            logger.debug("[%s][efc] Card parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_efinancialcareers(
    session: aiohttp.ClientSession,
    limiter: Any,
    quant_keywords: list[str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for keyword in quant_keywords:
        try:
            await limiter.acquire(PLATFORM)
            params: dict[str, str] = {
                "q": keyword,
                "type": "full-time",
            }
            async with session.get(
                _EFC_BASE_URL,
                params=params,
                headers=_build_headers(),
                allow_redirects=True,
            ) as resp:
                if resp.status == 429:
                    raise _RateLimitError()
                if resp.status != 200:
                    logger.warning(
                        "[%s][efc] Status %s for keyword=%r.", PLATFORM, resp.status, keyword
                    )
                    continue
                html = await resp.text()
                if _captcha_detected(html):
                    raise _CaptchaError()
                batch = _parse_efc_html(html, keyword)
                results.extend(batch)
                logger.debug(
                    "[%s][efc] keyword=%r → %d jobs.", PLATFORM, keyword, len(batch)
                )
        except (_RateLimitError, _CaptchaError):
            raise
        except aiohttp.ClientError as exc:
            logger.error("[%s][efc] Network error keyword=%r: %s", PLATFORM, keyword, exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s][efc] Unexpected error keyword=%r: %s", PLATFORM, keyword, exc)

    return results


# ---------------------------------------------------------------------------
# Source 2 — Braintrust
# ---------------------------------------------------------------------------

def _parse_braintrust_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    card_selectors = [
        "div[class*='JobCard']",
        "article[class*='job']",
        "li[class*='job']",
        "[data-testid='job-card']",
        "div[class*='job-item']",
        "div[class*='listing']",
    ]
    cards: list[Any] = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        container = soup.select_one(
            "div[class*='jobs-list'], ul[class*='jobs'], div#jobs-container"
        )
        if container:
            cards = container.find_all(["div", "li", "article"], recursive=False)

    for card in cards:
        try:
            title_el = card.select_one(
                "h2, h3, [class*='title'], [class*='Title'], a[class*='job']"
            )
            title = title_el.get_text(strip=True) if title_el else ""

            company_el = card.select_one(
                "[class*='company'], [class*='Company'], [class*='client'], span.org"
            )
            company = company_el.get_text(strip=True) if company_el else ""

            link_el = card.select_one("a[href]")
            url = ""
            if link_el:
                href = link_el.get("href", "")
                url = (
                    href
                    if href.startswith("http")
                    else f"https://app.usebraintrust.com{href}"
                )

            if not title or not url:
                continue

            # Filter: only keep quant/finance/AI roles
            combined = f"{title} {company}"
            if not _keyword_match(combined, _BRAINTRUST_FILTER_TERMS):
                continue

            salary_el = card.select_one(
                "[class*='salary'], [class*='rate'], [class*='pay'], [class*='budget']"
            )
            salary_text = salary_el.get_text(strip=True) if salary_el else ""

            desc_el = card.select_one(
                "[class*='description'], [class*='snippet'], [class*='summary']"
            )
            description = desc_el.get_text(strip=True) if desc_el else ""

            job_type_el = card.select_one(
                "[class*='type'], [class*='workType'], [class*='jobType']"
            )
            job_type = job_type_el.get_text(strip=True) if job_type_el else "freelance"

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
            logger.debug("[%s][braintrust] Card parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_braintrust(
    session: aiohttp.ClientSession,
    limiter: Any,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        await limiter.acquire(PLATFORM)
        async with session.get(
            _BRAINTRUST_URL,
            headers=_build_headers(),
            allow_redirects=True,
        ) as resp:
            if resp.status == 429:
                raise _RateLimitError()
            if resp.status != 200:
                logger.warning("[%s][braintrust] Status %s.", PLATFORM, resp.status)
                return results
            html = await resp.text()
            if _captcha_detected(html):
                raise _CaptchaError()
            results = _parse_braintrust_html(html)
            logger.debug("[%s][braintrust] %d jobs parsed.", PLATFORM, len(results))
    except (_RateLimitError, _CaptchaError):
        raise
    except aiohttp.ClientError as exc:
        logger.error("[%s][braintrust] Network error: %s", PLATFORM, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s][braintrust] Unexpected error: %s", PLATFORM, exc)
    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scrape(preferences: dict, limiter: Any) -> list[dict]:
    """
    Scrape niche finance job boards for quant / AI / finance roles.

    Parameters
    ----------
    preferences:
        Expected keys:
          - preferences["keywords"]["quant"]: list[str]  (used for eFinancialCareers)
    limiter:
        A RateLimiter with async acquire(platform) and set_pause(platform, seconds).

    Returns
    -------
    Combined list of normalised job dicts.
    """
    results: list[dict] = []
    keywords_map: dict[str, list[str]] = preferences.get("keywords", {})
    quant_keywords: list[str] = keywords_map.get("quant", _DEFAULT_QUANT_KEYWORDS)

    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # eFinancialCareers
        try:
            batch = await _scrape_efinancialcareers(session, limiter, quant_keywords)
            results.extend(batch)
        except _CaptchaError:
            logger.warning("[%s] CAPTCHA on eFinancialCareers — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except _RateLimitError:
            logger.warning("[%s] Rate-limited on eFinancialCareers — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Error in eFinancialCareers scraper: %s", PLATFORM, exc)

        # Braintrust
        try:
            batch = await _scrape_braintrust(session, limiter)
            results.extend(batch)
        except _CaptchaError:
            logger.warning("[%s] CAPTCHA on Braintrust — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except _RateLimitError:
            logger.warning("[%s] Rate-limited on Braintrust — pausing 7200 s.", PLATFORM)
            limiter.set_pause(PLATFORM, 7200)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Error in Braintrust scraper: %s", PLATFORM, exc)

    logger.info("[%s] Scraped %d jobs total.", PLATFORM, len(results))
    return results
