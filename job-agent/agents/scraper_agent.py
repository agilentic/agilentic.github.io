"""
scraper_agent.py
----------------
Runs all platform scrapers concurrently, deduplicates by URL hash,
inserts new jobs into the database, and returns the inserted records.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from db.database import Database
from platforms import (
    glassdoor,
    indeed,
    linkedin,
    niche_finance,
    real_estate,
    remote_boards,
    tutoring,
)
from utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Map platform name → scraper module (each must expose async scrape(preferences) -> List[dict])
_PLATFORM_MODULES: dict[str, Any] = {
    "linkedin": linkedin,
    "glassdoor": glassdoor,
    "indeed": indeed,
    "remote_boards": remote_boards,
    "niche_finance": niche_finance,
    "real_estate": real_estate,
    "tutoring": tutoring,
}


def _url_hash(url: str) -> str:
    """Return first 16 hex chars of SHA-256 of the URL — used as job primary key."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


async def _run_platform(
    name: str,
    module: Any,
    preferences: dict,
    limiter: RateLimiter,
) -> list[dict]:
    """Invoke a single platform scraper with rate-limiting, returning raw job dicts."""
    async with limiter:
        logger.info("Scraping platform: %s", name)
        results: list[dict] = await module.scrape(preferences)
        logger.info("Platform %s returned %d jobs", name, len(results))
        return results


async def scrape_all_platforms(
    preferences: dict,
    db: Database,
    limiter: RateLimiter,
) -> list[dict]:
    """
    Run all platform scrapers concurrently.

    Args:
        preferences: Job-search preferences (domains, keywords, job_types, etc.).
        db:          Initialised Database instance.
        limiter:     Shared RateLimiter applied per platform invocation.

    Returns:
        List of newly inserted job dicts (jobs that were not already in the DB).
    """
    tasks = {
        name: asyncio.create_task(
            _run_platform(name, module, preferences, limiter),
            name=f"scrape_{name}",
        )
        for name, module in _PLATFORM_MODULES.items()
    }

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    # Flatten all job dicts, skipping platforms that raised exceptions
    all_jobs: list[dict] = []
    for name, result in zip(tasks.keys(), results):
        if isinstance(result, BaseException):
            logger.warning(
                "Platform '%s' raised an exception (skipping): %s: %s",
                name,
                type(result).__name__,
                result,
            )
        else:
            all_jobs.extend(result)

    logger.info("Total raw jobs collected across all platforms: %d", len(all_jobs))

    # Deduplicate by URL hash within this batch
    seen_hashes: set[str] = set()
    unique_jobs: list[dict] = []
    for job in all_jobs:
        url = job.get("url", "")
        if not url:
            logger.warning("Job missing URL, skipping: %s", job)
            continue
        h = _url_hash(url)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        job["id"] = h
        unique_jobs.append(job)

    logger.info("Unique jobs after in-batch deduplication: %d", len(unique_jobs))

    # Insert into DB — insert_job returns True only for newly inserted rows
    newly_inserted: list[dict] = []
    for job in unique_jobs:
        try:
            inserted = await db.insert_job(job)
            if inserted:
                newly_inserted.append(job)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to insert job '%s' (%s): %s",
                job.get("title", "?"),
                job.get("url", "?"),
                exc,
            )

    logger.info(
        "Newly inserted jobs: %d (skipped %d duplicates already in DB)",
        len(newly_inserted),
        len(unique_jobs) - len(newly_inserted),
    )
    return newly_inserted
