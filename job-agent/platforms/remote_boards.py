"""
Remote job boards scraper — aggregates three public sources:

1. We Work Remotely RSS  (https://weworkremotely.com/remote-jobs.rss)
2. Remote.co HTML        (https://remote.co/remote-jobs/)
3. Remotive JSON API     (https://remotive.com/api/remote-jobs?category=software-dev)

Results are filtered to match preference keywords and merged into one list.
"""

from __future__ import annotations

import hashlib
import logging
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PLATFORM = "remote_boards"

_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

_WWR_RSS_URL = "https://weworkremotely.com/remote-jobs.rss"
_REMOTECO_URL = "https://remote.co/remote-jobs/"
_REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"


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
    """Return True if any keyword appears in *text* (case-insensitive)."""
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


def _flatten_keywords(preferences: dict) -> list[str]:
    keywords_map: dict[str, list[str]] = preferences.get("keywords", {})
    seen: set[str] = set()
    result: list[str] = []
    for kw_list in keywords_map.values():
        for kw in kw_list:
            if kw not in seen:
                result.append(kw)
                seen.add(kw)
    return result


# ---------------------------------------------------------------------------
# Source 1 — We Work Remotely RSS
# ---------------------------------------------------------------------------

def _parse_wwr_rss(xml_text: str, keywords: list[str]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("[%s][wwr] XML parse error: %s", PLATFORM, exc)
        return jobs

    # RSS 2.0: <rss><channel><item>…</item></channel></rss>
    ns = ""
    channel = root.find("channel")
    if channel is None:
        return jobs

    for item in channel.findall("item"):
        def _text(tag: str) -> str:
            el = item.find(tag)
            return (el.text or "").strip() if el is not None else ""

        title = _text("title")
        link = _text("link")
        description = _text("description")
        company = ""

        # WWR encodes "<company>: <title>" in the <title> element
        if ": " in title:
            parts = title.split(": ", 1)
            company, title = parts[0].strip(), parts[1].strip()

        combined = f"{title} {company} {description}"
        if keywords and not _keyword_match(combined, keywords):
            continue

        if not title or not link:
            continue

        jobs.append({
            "id": make_job_id(link, title, company),
            "title": title,
            "company": company,
            "url": link,
            "platform": PLATFORM,
            "description": description,
            "salary_text": "",
            "job_type": "remote",
            "discovered_at": _now_iso(),
        })

    return jobs


async def _scrape_wwr(
    session: aiohttp.ClientSession, limiter: Any, keywords: list[str]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        await limiter.acquire(PLATFORM)
        async with session.get(
            _WWR_RSS_URL,
            headers=_build_headers("application/rss+xml, application/xml, text/xml, */*"),
        ) as resp:
            if resp.status == 429:
                logger.warning("[%s][wwr] 429 — raising for caller.", PLATFORM)
                raise _RateLimitError()
            if resp.status != 200:
                logger.warning("[%s][wwr] Status %s.", PLATFORM, resp.status)
                return results
            xml_text = await resp.text()
            if _captcha_detected(xml_text):
                raise _CaptchaError()
            results = _parse_wwr_rss(xml_text, keywords)
            logger.debug("[%s][wwr] %d jobs parsed.", PLATFORM, len(results))
    except (_RateLimitError, _CaptchaError):
        raise
    except aiohttp.ClientError as exc:
        logger.error("[%s][wwr] Network error: %s", PLATFORM, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s][wwr] Unexpected error: %s", PLATFORM, exc)
    return results


# ---------------------------------------------------------------------------
# Source 2 — Remote.co HTML
# ---------------------------------------------------------------------------

def _parse_remoteco_html(html: str, keywords: list[str]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, Any]] = []

    # Job cards: <div class="card"> or <li class="job-listing"> variants
    card_selectors = [
        "div.job_listing",
        "li.job_listing",
        ".card.job",
        "[class*='job-listing']",
        "article.job",
    ]
    cards: list[Any] = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        # Fallback: look for a <ul> or <div> that holds job rows
        container = soup.select_one("ul.jobs, div#job-listings, div.jobs-container")
        if container:
            cards = container.find_all(["li", "div"], recursive=False)

    for card in cards:
        try:
            title_el = card.select_one(
                "h2 a, h3 a, .job-title a, .position a, a.job_listing-clickable"
            )
            if not title_el:
                title_el = card.select_one("h2, h3, .job-title, .position")
            title = title_el.get_text(strip=True) if title_el else ""

            company_el = card.select_one(
                ".company, .company_name, [class*='company']"
            )
            company = company_el.get_text(strip=True) if company_el else ""

            link_el = card.select_one("a[href]")
            url = ""
            if link_el:
                href = link_el.get("href", "")
                url = href if href.startswith("http") else f"https://remote.co{href}"

            if not title or not url:
                continue

            combined = f"{title} {company}"
            if keywords and not _keyword_match(combined, keywords):
                continue

            jobs.append({
                "id": make_job_id(url, title, company),
                "title": title,
                "company": company,
                "url": url,
                "platform": PLATFORM,
                "description": "",
                "salary_text": "",
                "job_type": "remote",
                "discovered_at": _now_iso(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s][remoteco] Card parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_remoteco(
    session: aiohttp.ClientSession, limiter: Any, keywords: list[str]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        await limiter.acquire(PLATFORM)
        async with session.get(
            _REMOTECO_URL,
            headers=_build_headers(),
            allow_redirects=True,
        ) as resp:
            if resp.status == 429:
                raise _RateLimitError()
            if resp.status != 200:
                logger.warning("[%s][remoteco] Status %s.", PLATFORM, resp.status)
                return results
            html = await resp.text()
            if _captcha_detected(html):
                raise _CaptchaError()
            results = _parse_remoteco_html(html, keywords)
            logger.debug("[%s][remoteco] %d jobs parsed.", PLATFORM, len(results))
    except (_RateLimitError, _CaptchaError):
        raise
    except aiohttp.ClientError as exc:
        logger.error("[%s][remoteco] Network error: %s", PLATFORM, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s][remoteco] Unexpected error: %s", PLATFORM, exc)
    return results


# ---------------------------------------------------------------------------
# Source 3 — Remotive JSON API
# ---------------------------------------------------------------------------

def _parse_remotive_json(data: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    job_list = data.get("jobs", [])
    if not isinstance(job_list, list):
        return jobs

    for item in job_list:
        if not isinstance(item, dict):
            continue
        try:
            title: str = (item.get("title") or "").strip()
            company: str = (item.get("company_name") or "").strip()
            url: str = (item.get("url") or "").strip()
            description: str = (item.get("description") or "").strip()
            salary_text: str = (item.get("salary") or "").strip()
            job_type: str = (item.get("job_type") or "remote").strip()

            if not title or not url:
                continue

            combined = f"{title} {company} {description}"
            if keywords and not _keyword_match(combined, keywords):
                continue

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
            logger.debug("[%s][remotive] Item parse error: %s", PLATFORM, exc)

    return jobs


async def _scrape_remotive(
    session: aiohttp.ClientSession, limiter: Any, keywords: list[str]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        await limiter.acquire(PLATFORM)
        async with session.get(
            _REMOTIVE_API_URL,
            params={"category": "software-dev"},
            headers=_build_headers("application/json, */*"),
        ) as resp:
            if resp.status == 429:
                raise _RateLimitError()
            if resp.status != 200:
                logger.warning("[%s][remotive] Status %s.", PLATFORM, resp.status)
                return results
            text = await resp.text()
            if _captcha_detected(text):
                raise _CaptchaError()
            import json
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                logger.error("[%s][remotive] JSON decode error: %s", PLATFORM, exc)
                return results
            results = _parse_remotive_json(data, keywords)
            logger.debug("[%s][remotive] %d jobs parsed.", PLATFORM, len(results))
    except (_RateLimitError, _CaptchaError):
        raise
    except aiohttp.ClientError as exc:
        logger.error("[%s][remotive] Network error: %s", PLATFORM, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s][remotive] Unexpected error: %s", PLATFORM, exc)
    return results


# ---------------------------------------------------------------------------
# Internal sentinel exceptions
# ---------------------------------------------------------------------------

class _RateLimitError(Exception):
    pass


class _CaptchaError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scrape(preferences: dict, limiter: Any) -> list[dict]:
    """
    Aggregate remote job listings from We Work Remotely, Remote.co, and Remotive.

    Parameters
    ----------
    preferences:
        Must contain:
          - preferences["keywords"]: dict[str, list[str]]
    limiter:
        A RateLimiter with async acquire(platform) and set_pause(platform, seconds).

    Returns
    -------
    Combined list of normalised job dicts filtered by preference keywords.
    """
    results: list[dict] = []
    keywords = _flatten_keywords(preferences)

    if not keywords:
        logger.warning("[%s] No keywords found in preferences.", PLATFORM)

    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        for scrape_fn in (_scrape_wwr, _scrape_remoteco, _scrape_remotive):
            try:
                batch = await scrape_fn(session, limiter, keywords)
                results.extend(batch)
            except _CaptchaError:
                logger.warning("[%s] CAPTCHA detected — pausing 7200 s.", PLATFORM)
                limiter.set_pause(PLATFORM, 7200)
                return results
            except _RateLimitError:
                logger.warning("[%s] Rate-limited — pausing 7200 s.", PLATFORM)
                limiter.set_pause(PLATFORM, 7200)
                return results
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] Unexpected error in %s: %s", PLATFORM, scrape_fn.__name__, exc)

    logger.info("[%s] Scraped %d jobs total.", PLATFORM, len(results))
    return results
