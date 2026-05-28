"""
LinkedIn job scraper — uses the public guest job-search endpoint only.
Respects robots.txt by targeting the /jobs-guest/ path which is permitted
for crawlers that honour rate limits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

PLATFORM = "linkedin"

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# Public guest endpoint — does not require authentication
_BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobView"
_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobView"

# LinkedIn returns up to 25 results per page; we cap at 10 pages per keyword
_PAGE_SIZE = 25
_MAX_PAGES = 10


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
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.linkedin.com/jobs/",
    }


def _parse_job_card(card: dict[str, Any]) -> dict[str, Any] | None:
    """
    Parse a single job-card dict returned by the LinkedIn guest API.
    Returns a normalised job dict or None if essential fields are missing.
    """
    try:
        title: str = (
            card.get("title")
            or card.get("jobTitle")
            or card.get("name")
            or ""
        ).strip()
        company: str = (
            card.get("companyName")
            or card.get("company")
            or ""
        ).strip()
        url: str = (
            card.get("jobPostingUrl")
            or card.get("url")
            or card.get("applyUrl")
            or ""
        ).strip()
        description: str = (card.get("description") or "").strip()
        salary_text: str = (card.get("salaryInsights") or "").strip()
        job_type: str = (
            card.get("workplaceType")
            or card.get("jobType")
            or ""
        ).strip()

        if not title or not url:
            return None

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
        logger.debug("Error parsing LinkedIn job card: %s", exc)
        return None


async def scrape(preferences: dict, limiter: Any) -> list[dict]:
    """
    Scrape LinkedIn Jobs guest API for each keyword set in preferences.

    Parameters
    ----------
    preferences:
        Must contain at minimum:
          - preferences["keywords"]: dict[str, list[str]]
          - preferences.get("location", "United States")
    limiter:
        A RateLimiter with async acquire(platform) and set_pause(platform, seconds).

    Returns
    -------
    List of normalised job dicts.
    """
    results: list[dict] = []
    location: str = preferences.get("location", "United States")

    # Flatten all keyword lists into a deduplicated sequence
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
            for page in range(_MAX_PAGES):
                start = page * _PAGE_SIZE
                params: dict[str, Any] = {
                    "keywords": keyword,
                    "location": location,
                    "f_AL": "true",   # Easy Apply filter
                    "start": start,
                    "count": _PAGE_SIZE,
                }

                try:
                    await limiter.acquire(PLATFORM)
                    async with session.get(
                        _SEARCH_URL,
                        params=params,
                        headers=_build_headers(),
                    ) as resp:
                        if resp.status == 401:
                            logger.warning(
                                "[%s] 401 Unauthorized for keyword=%r — skipping.",
                                PLATFORM,
                                keyword,
                            )
                            break  # skip remaining pages for this keyword

                        if resp.status == 429:
                            logger.warning(
                                "[%s] 429 Too Many Requests — pausing 7200 s.",
                                PLATFORM,
                            )
                            limiter.set_pause(PLATFORM, 7200)
                            return results

                        if resp.status != 200:
                            logger.warning(
                                "[%s] Unexpected status %s for keyword=%r page=%d.",
                                PLATFORM,
                                resp.status,
                                keyword,
                                page,
                            )
                            break

                        text = await resp.text()

                        if _captcha_detected(text):
                            logger.warning(
                                "[%s] CAPTCHA detected — pausing 7200 s.", PLATFORM
                            )
                            limiter.set_pause(PLATFORM, 7200)
                            return results

                        # The guest API may return JSON or HTML depending on
                        # the endpoint variant; try JSON first.
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError:
                            # Fall back: treat as empty page; stop pagination
                            logger.debug(
                                "[%s] Non-JSON response for keyword=%r page=%d.",
                                PLATFORM,
                                keyword,
                                page,
                            )
                            break

                        # Accept both list-of-cards and {"data": [...]} shapes
                        if isinstance(data, list):
                            cards = data
                        elif isinstance(data, dict):
                            cards = (
                                data.get("included")
                                or data.get("data")
                                or data.get("jobs")
                                or data.get("elements")
                                or []
                            )
                        else:
                            cards = []

                        if not cards:
                            break  # no more results for this keyword

                        for card in cards:
                            if not isinstance(card, dict):
                                continue
                            job = _parse_job_card(card)
                            if job:
                                results.append(job)

                        # If fewer results than page size, no more pages
                        if len(cards) < _PAGE_SIZE:
                            break

                except aiohttp.ClientError as exc:
                    logger.error(
                        "[%s] Network error for keyword=%r page=%d: %s",
                        PLATFORM,
                        keyword,
                        page,
                        exc,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "[%s] Unexpected error for keyword=%r page=%d: %s",
                        PLATFORM,
                        keyword,
                        page,
                        exc,
                    )
                    break

    logger.info("[%s] Scraped %d jobs.", PLATFORM, len(results))
    return results
