"""
tracker_agent.py — Email response polling and job status state machine.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

from db.database import Database
from utils.email_reader import poll_inbox
from utils.llm import chat_json

logger = logging.getLogger(__name__)

_CLASSIFY_SYSTEM = (
    "You are an email classifier for job applications. "
    "Classify the email as exactly one of: "
    "'rejection' | 'interview_request' | 'info_request' | 'offer' | 'unrelated'. "
    "Output JSON only: {\"type\": \"...\", \"key_info\": \"<one sentence summary>\"}"
)

_STATUS_MAP = {
    "rejection": "rejected",
    "interview_request": "interview",
    "offer": "offer",
}


async def poll_responses(email_config: dict[str, Any], db: Database) -> list[dict]:
    """
    Poll Gmail for new application-related emails, classify each with Claude,
    update DB job statuses, and return a list of processed response records.
    """
    gmail_address: str = email_config.get("gmail_address", "")
    app_password: str = email_config.get("gmail_app_password", "")

    if not gmail_address or not app_password:
        logger.warning("Gmail credentials not configured — skipping email poll")
        return []

    emails = await poll_inbox(gmail_address, app_password, since_hours=2)
    logger.info("Polled %d emails from Gmail", len(emails))

    processed: list[dict] = []

    # Build a map of company-domain → job_id from recent applied jobs
    domain_to_job: dict[str, str] = {}
    applied_jobs = await db.get_jobs_by_status("applied")
    for job in applied_jobs:
        company_domain = _extract_domain(job.get("company", ""))
        if company_domain:
            domain_to_job[company_domain] = job["id"]

    tasks = [_process_email(email, domain_to_job, db) for email in emails]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.error("Error processing email: %s", result)
        elif result is not None:
            processed.append(result)

    logger.info("Processed %d actionable responses", len(processed))
    return processed


async def _process_email(
    email: dict,
    domain_to_job: dict[str, str],
    db: Database,
) -> dict | None:
    """Classify one email and update DB if it matches a known application."""
    from_addr: str = email.get("from_addr", "")
    subject: str = email.get("subject", "")
    body: str = email.get("body", "")[:3000]  # cap to avoid token overflow

    user_msg = f"From: {from_addr}\nSubject: {subject}\n\nBody:\n{body}"
    try:
        result = await chat_json(
            system=_CLASSIFY_SYSTEM,
            user=user_msg,
            schema_keys=["type", "key_info"],
        )
    except Exception as exc:
        logger.error("LLM classification failed for email from %s: %s", from_addr, exc)
        return None

    email_type: str = result.get("type", "unrelated")
    key_info: str = result.get("key_info", "")

    if email_type == "unrelated":
        return None

    # Match sender domain to a known job
    sender_domain = _extract_domain(from_addr)
    job_id = domain_to_job.get(sender_domain)

    response_record = {
        "job_id": job_id,
        "received_at": email.get("received_at", datetime.utcnow().isoformat()),
        "response_type": email_type,
        "raw_email": f"Subject: {subject}\nFrom: {from_addr}\n\n{body}",
    }
    await db.insert_response(response_record)

    if job_id and email_type in _STATUS_MAP:
        new_status = _STATUS_MAP[email_type]
        await db.update_job_status(job_id, new_status)
        logger.info("Job %s → status=%s (%s)", job_id[:8], new_status, key_info)

    if email_type == "interview_request":
        _log_interview(from_addr, subject, key_info)

    return {**response_record, "key_info": key_info, "from": from_addr, "subject": subject}


def _extract_domain(address: str) -> str:
    """Extract bare domain from an email address or company name."""
    if "@" in address:
        return address.split("@")[-1].lower().strip(">").strip()
    # Fallback: normalise company name to likely domain
    return address.lower().replace(" ", "").replace(",", "").replace(".", "")[:30]


def _log_interview(from_addr: str, subject: str, key_info: str) -> None:
    import os
    os.makedirs("logs", exist_ok=True)
    with open("logs/interviews.log", "a") as fh:
        fh.write(
            f"[{datetime.utcnow().isoformat()}] FROM={from_addr} | "
            f"SUBJECT={subject} | INFO={key_info}\n"
        )


async def write_daily_digest(db: Database, date_str: str | None = None) -> None:
    """Write a human-readable daily summary to logs/daily_digest_{date}.txt."""
    import os
    os.makedirs("logs", exist_ok=True)

    if date_str is None:
        date_str = date.today().isoformat()

    stats = await db.get_daily_stats()
    applied_today = await db.get_applications_today()

    lines = [
        f"Daily Job-Agent Digest — {date_str}",
        "=" * 50,
        f"Applications sent today : {applied_today}",
        f"Total applied (all time): {stats.get('applied', 0)}",
        f"Interviews              : {stats.get('interview', 0)}",
        f"Rejections              : {stats.get('rejected', 0)}",
        f"Offers                  : {stats.get('offer', 0)}",
        f"Pending / queued        : {stats.get('queued', 0)}",
        "",
    ]

    recent = await db.get_jobs_by_status("applied")
    if recent:
        lines.append("Recent applications:")
        for job in recent[-10:]:
            lines.append(
                f"  [{job.get('relevance_score', 0):.2f}] "
                f"{job.get('title')} @ {job.get('company')} "
                f"({job.get('platform')}) — {job.get('status')}"
            )

    digest_path = f"logs/daily_digest_{date_str}.txt"
    with open(digest_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    logger.info("Daily digest written to %s", digest_path)
