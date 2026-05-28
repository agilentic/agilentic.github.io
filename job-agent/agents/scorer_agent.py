"""
scorer_agent.py
---------------
LLM-backed job relevance scorer with hard filters applied before any API call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from utils.llm import chat_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_JOB_AGE_DAYS = 180

_SCORE_SYSTEM_PROMPT = (
    "You are a precise job relevance scorer. Given a job description and a candidate "
    "profile, output ONLY a JSON object with these fields: "
    "{\"score\": <float 0.0-1.0>, "
    "\"domain\": <\"ai_ml\"|\"quant\"|\"real_estate\"|\"tutoring\"|\"other\">, "
    "\"reasoning\": <one sentence>, "
    "\"ats_keywords\": [<list of top 8 JD keywords>], "
    "\"red_flags\": [<list of dealbreakers if any>]}. "
    "Score 0.85+ only if: role is a strong match for stated domains, meets experience "
    "level, and salary/type aligns. Output valid JSON only."
)

_SCORE_SCHEMA_KEYS = ["score", "domain", "reasoning", "ats_keywords", "red_flags"]

# Regex to extract a dollar amount that may be labelled as a maximum
_SALARY_MAX_RE = re.compile(
    r"(?:up\s+to|max(?:imum)?|to)\s*\$?([\d,]+)",
    re.IGNORECASE,
)
_SALARY_PLAIN_RE = re.compile(r"\$?([\d,]+)\s*[-–]\s*\$?([\d,]+)")


# ---------------------------------------------------------------------------
# Hard-filter helpers
# ---------------------------------------------------------------------------


def _is_too_old(job: dict) -> bool:
    discovered_at = job.get("discovered_at")
    if not discovered_at:
        return False
    try:
        if isinstance(discovered_at, str):
            # Handle both "Z" suffix and offset-aware strings
            discovered_at = discovered_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(discovered_at)
        elif isinstance(discovered_at, datetime):
            dt = discovered_at
        else:
            return False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).days
        return age_days > _MAX_JOB_AGE_DAYS
    except (ValueError, TypeError):
        return False


def _is_blacklisted(job: dict, profile: dict) -> bool:
    company = (job.get("company") or "").strip().lower()
    blacklist: list[str] = [
        c.strip().lower()
        for c in profile.get("blacklist_companies", [])
    ]
    return company in blacklist


def _has_excluded_title_term(job: dict) -> bool:
    """Return True if title contains disqualifying terms (except tutoring domain)."""
    domain = (job.get("domain") or "").lower()
    if domain == "tutoring":
        return False
    title = (job.get("title") or "").lower()
    excluded = ("intern", "unpaid", "volunteer")
    return any(term in title for term in excluded)


def _salary_below_minimum(job: dict, profile: dict) -> bool:
    """Return True if salary_text contains an explicit maximum below profile minimum."""
    salary_text = job.get("salary_text") or ""
    if not salary_text:
        return False
    salary_min_usd: int = profile.get("salary_min_usd", 0)
    if salary_min_usd <= 0:
        return False

    # Try to find explicit "up to $X" or "max $X" pattern
    max_match = _SALARY_MAX_RE.search(salary_text)
    if max_match:
        try:
            cap = int(max_match.group(1).replace(",", ""))
            return cap < salary_min_usd
        except ValueError:
            pass

    # Try plain range "X – Y"; check if upper bound is below minimum
    range_match = _SALARY_PLAIN_RE.search(salary_text)
    if range_match:
        try:
            upper = int(range_match.group(2).replace(",", ""))
            return upper < salary_min_usd
        except ValueError:
            pass

    return False


def _zero_result(reason: str) -> dict:
    return {
        "score": 0.0,
        "domain": "other",
        "reasoning": reason,
        "ats_keywords": [],
        "red_flags": [reason],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def score_job(
    job: dict,
    profile: dict,
    limiter_llm: Any = None,
) -> dict:
    """
    Score a single job against a candidate profile.

    Hard filters are applied first; if any trigger the function returns
    immediately with score=0.0 without calling the LLM.

    Args:
        job:         Job record dict (fields per DB schema).
        profile:     Candidate profile dict (from config.yaml profile + job_preferences).
        limiter_llm: Optional rate-limiter; if provided, used as async context manager
                     before the LLM call.

    Returns:
        Dict with keys: score, domain, reasoning, ats_keywords, red_flags.
    """
    # ── Hard filters ──────────────────────────────────────────────────────
    if _is_too_old(job):
        return _zero_result("Job is older than 180 days")

    if _is_blacklisted(job, profile):
        return _zero_result(f"Company '{job.get('company')}' is blacklisted")

    if _has_excluded_title_term(job):
        return _zero_result("Title contains excluded term (intern/unpaid/volunteer)")

    if _salary_below_minimum(job, profile):
        return _zero_result("Advertised salary maximum is below candidate minimum")

    # ── LLM scoring ───────────────────────────────────────────────────────
    user_prompt = (
        f"Job Title: {job.get('title', 'N/A')}\n"
        f"Company: {job.get('company', 'N/A')}\n"
        f"Platform: {job.get('platform', 'N/A')}\n"
        f"Salary: {job.get('salary_text', 'not listed')}\n"
        f"Job Type: {job.get('job_type', 'N/A')}\n\n"
        f"Description:\n{job.get('description', 'No description provided.')}\n\n"
        f"---\n"
        f"Candidate Profile:\n"
        f"Domains: {json.dumps(profile.get('domains', []))}\n"
        f"Experience Level: {json.dumps(profile.get('experience_level', []))}\n"
        f"Salary Minimum: ${profile.get('salary_min_usd', 0):,}\n"
        f"Job Types: {json.dumps(profile.get('job_types', []))}\n"
        f"Remote Preference: {profile.get('remote_preference', 'any')}"
    )

    try:
        if limiter_llm is not None:
            async with limiter_llm:
                result = await chat_json(_SCORE_SYSTEM_PROMPT, user_prompt, _SCORE_SCHEMA_KEYS)
        else:
            result = await chat_json(_SCORE_SYSTEM_PROMPT, user_prompt, _SCORE_SCHEMA_KEYS)
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM scoring failed for job '%s': %s", job.get("title"), exc)
        return _zero_result(f"LLM error: {exc}")

    # Normalise / validate returned dict
    result.setdefault("score", 0.0)
    result.setdefault("domain", "other")
    result.setdefault("reasoning", "")
    result.setdefault("ats_keywords", [])
    result.setdefault("red_flags", [])

    try:
        result["score"] = float(result["score"])
        result["score"] = max(0.0, min(1.0, result["score"]))
    except (TypeError, ValueError):
        result["score"] = 0.0

    logger.debug(
        "Scored '%s' @ %.2f (domain=%s)",
        job.get("title"),
        result["score"],
        result["domain"],
    )
    return result


async def score_batch(
    jobs: list[dict],
    profile: dict,
    batch_size: int = 10,
) -> list[dict]:
    """
    Score a list of jobs in concurrent batches.

    Args:
        jobs:       List of job dicts to score.
        profile:    Candidate profile dict.
        batch_size: Number of jobs scored concurrently per batch.

    Returns:
        List of scorer result dicts, in the same order as `jobs`.
    """
    all_results: list[dict] = []

    for batch_start in range(0, len(jobs), batch_size):
        batch = jobs[batch_start : batch_start + batch_size]
        logger.info(
            "Scoring batch %d–%d of %d",
            batch_start + 1,
            batch_start + len(batch),
            len(jobs),
        )
        batch_results = await asyncio.gather(
            *[score_job(job, profile) for job in batch],
            return_exceptions=True,
        )
        for job, result in zip(batch, batch_results):
            if isinstance(result, BaseException):
                logger.warning(
                    "score_job raised for '%s': %s",
                    job.get("title"),
                    result,
                )
                all_results.append(_zero_result(f"Unhandled exception: {result}"))
            else:
                all_results.append(result)

    return all_results
