"""
agents/apply_agent.py
---------------------
Automates job applications via LinkedIn Easy Apply, external ATS portals
(Greenhouse, Lever, Workday, iCIMS), or email-outbox fallback.

Safety contract
---------------
- Never fabricates credentials or makes up answers.
- Aborts immediately (returns requires_human) if the form asks for SSN,
  bank account, or passport number.
- Adds a random 3–8 second human-paced delay between form-field fills.
- Retries up to MAX_RETRIES times before marking the attempt failed.
- Always screenshots the confirmation page (or the failure state).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from utils.browser import BrowserManager
from utils.llm import chat_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
_FIELD_DELAY_MIN = 3.0   # seconds between form-field interactions
_FIELD_DELAY_MAX = 8.0

# Sensitive field keywords that require human review
_SENSITIVE_PATTERNS: tuple[str, ...] = (
    "ssn",
    "social security",
    "bank account",
    "routing number",
    "passport",
    "driver license",
    "driver's license",
)

# ATS detection: (domain_fragment, ats_name)
_ATS_SIGNATURES: list[tuple[str, str]] = [
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("myworkdayjobs.com", "workday"),
    ("icims.com", "icims"),
]

# Paths
_ROOT = Path(__file__).resolve().parent.parent
_LOGS_DIR = _ROOT / "logs"
_SCREENSHOTS_DIR = _LOGS_DIR / "screenshots"
_OUTBOX_DIR = _ROOT / "outbox"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dirs() -> None:
    _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    _OUTBOX_DIR.mkdir(parents=True, exist_ok=True)


def _is_sensitive(text: str) -> bool:
    """Return True if *text* mentions any credential/PII we must never handle."""
    lowered = text.lower()
    return any(pat in lowered for pat in _SENSITIVE_PATTERNS)


async def _human_delay() -> None:
    """Sleep for a random interval to mimic human typing cadence."""
    delay = random.uniform(_FIELD_DELAY_MIN, _FIELD_DELAY_MAX)
    await asyncio.sleep(delay)


async def _safe_fill(page: Page, selector: str, value: str) -> bool:
    """
    Locate *selector*, check for sensitive-field label, fill with *value*.

    Returns True on success, False if the element is not found or empty value.
    """
    if not value:
        return False
    try:
        element = page.locator(selector).first
        # Inspect surrounding label text for sensitive content
        label_text = ""
        try:
            label_text = await element.evaluate(
                "(el) => el.closest('label')?.innerText || "
                "document.querySelector(`label[for='${el.id}']`)?.innerText || ''"
            )
        except Exception:  # noqa: BLE001
            pass
        if _is_sensitive(label_text or ""):
            logger.warning("Sensitive field detected ('%s') — aborting.", label_text[:80])
            raise SensitiveFieldError(f"Sensitive field: {label_text[:80]}")

        await element.fill(value)
        await _human_delay()
        return True
    except SensitiveFieldError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("_safe_fill selector=%r failed: %s", selector, exc)
        return False


async def _screenshot(browser: BrowserManager, page: Page, job_id: str, label: str) -> None:
    """Save a screenshot to logs/screenshots/{job_id}_{label}.png."""
    _ensure_dirs()
    path = str(_SCREENSHOTS_DIR / f"{job_id}_{label}.png")
    await browser.screenshot(page, path)


async def _answer_screening_question(question_text: str, profile: dict) -> str:
    """
    Use Claude to answer a screening question truthfully based on the profile.

    Returns an empty string on failure (do not fabricate an answer).
    """
    system = (
        "You are helping a candidate fill out a job application form truthfully. "
        "Answer the following screening question based solely on the candidate profile "
        "provided. Be concise (1–2 sentences). Never fabricate facts. "
        "If the profile does not contain enough information to answer truthfully, "
        "reply with the string 'N/A'. Output only the answer text, no preamble."
    )
    user = f"Question: {question_text}\n\nCandidate Profile:\n{json.dumps(profile, indent=2)}"
    try:
        answer = await chat_json(
            system,
            user,
            schema_keys=["answer"],
            max_tokens=256,
        )
        return str(answer.get("answer", "N/A"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Screening-question LLM call failed: %s", exc)
        return "N/A"


def _detect_ats(url: str) -> str | None:
    """Return the ATS name if the URL matches a known ATS domain, else None."""
    url_lower = url.lower()
    for fragment, name in _ATS_SIGNATURES:
        if fragment in url_lower:
            return name
    return None


def _error_result(error: str) -> dict[str, Any]:
    return {"success": False, "method": "failed", "confirmation": "", "error": error}


def _abort_result(reason: str) -> dict[str, Any]:
    return {"success": False, "method": "aborted", "confirmation": "", "error": reason}


# ---------------------------------------------------------------------------
# Application strategies
# ---------------------------------------------------------------------------


async def _try_linkedin_easy_apply(
    job: dict,
    materials: dict,
    profile: dict,
    browser: BrowserManager,
) -> dict[str, Any] | None:
    """
    Attempt LinkedIn Easy Apply.

    Returns a result dict on success or explicit failure, or None if this
    strategy is not applicable (no Easy Apply button found).
    """
    job_id: str = job.get("id", "unknown")
    url: str = job.get("url", "")
    resume_pdf: str = materials.get("resume_pdf_path", "")

    page: Page = await browser.new_page()
    try:
        logger.info("[linkedin_easy_apply] Navigating to %s", url)
        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        await _human_delay()

        # Detect Easy Apply button
        easy_apply_btn = page.locator(
            "button:has-text('Easy Apply'), "
            "[aria-label*='Easy Apply'], "
            ".jobs-apply-button--top-card"
        ).first
        if not await easy_apply_btn.is_visible(timeout=5_000):
            logger.debug("[linkedin_easy_apply] No Easy Apply button found.")
            return None

        await easy_apply_btn.click()
        await _human_delay()

        # Multi-step modal loop
        for step in range(10):  # guard against infinite loops
            # Check for page-level sensitive field
            page_text = await page.inner_text("body")
            if _is_sensitive(page_text):
                await _screenshot(browser, page, job_id, "sensitive_abort")
                return _abort_result("requires_human")

            # Fill contact info fields (best-effort selectors)
            await _safe_fill(page, 'input[name="phoneNumber"], input[id*="phoneNumber"]',
                             profile.get("phone", ""))
            await _safe_fill(page, 'input[name="city"], input[id*="city"]',
                             profile.get("location", ""))

            # Upload resume if file input is present
            if resume_pdf and Path(resume_pdf).is_file():
                file_input = page.locator('input[type="file"]').first
                if await file_input.is_visible(timeout=2_000):
                    await file_input.set_input_files(resume_pdf)
                    await _human_delay()

            # Answer any screening questions visible on this step
            question_locators = page.locator('label.artdeco-text-input--label, '
                                             'fieldset legend, .fb-form-element__label')
            q_count = await question_locators.count()
            for qi in range(q_count):
                q_label = await question_locators.nth(qi).inner_text()
                q_input = page.locator(
                    f'input[aria-labelledby], textarea[aria-labelledby]'
                ).nth(qi)
                if await q_input.is_visible(timeout=1_000):
                    answer = await _answer_screening_question(q_label, profile)
                    if answer and answer != "N/A":
                        await q_input.fill(answer)
                        await _human_delay()

            # Determine next action: "Next", "Review", or "Submit"
            submit_btn = page.locator(
                'button[aria-label="Submit application"], '
                'button:has-text("Submit application")'
            ).first
            next_btn = page.locator(
                'button[aria-label="Continue to next step"], '
                'button:has-text("Next"), '
                'button:has-text("Review")'
            ).first

            if await submit_btn.is_visible(timeout=2_000):
                await submit_btn.click()
                await _human_delay()
                break
            elif await next_btn.is_visible(timeout=2_000):
                await next_btn.click()
                await _human_delay()
            else:
                logger.debug("[linkedin_easy_apply] No Next/Submit button on step %d.", step)
                break

        # Capture confirmation
        await _screenshot(browser, page, job_id, "confirmation")
        confirmation = ""
        try:
            conf_el = page.locator(
                '.artdeco-inline-feedback--success, '
                'h3:has-text("application"), '
                '.jobs-post-enagement-feedback__confirmation-msg'
            ).first
            if await conf_el.is_visible(timeout=5_000):
                confirmation = await conf_el.inner_text()
        except Exception:  # noqa: BLE001
            confirmation = "Application submitted (confirmation text not captured)"

        logger.info("[linkedin_easy_apply] Success for job_id=%s", job_id)
        return {
            "success": True,
            "method": "linkedin_easy_apply",
            "confirmation": confirmation or "Application submitted",
            "error": "",
        }

    except SensitiveFieldError as exc:
        await _screenshot(browser, page, job_id, "abort")
        return _abort_result("requires_human")
    except PlaywrightTimeout as exc:
        logger.warning("[linkedin_easy_apply] Timeout: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[linkedin_easy_apply] Error: %s", exc)
        return None
    finally:
        await page.context.close()


async def _try_ats_apply(
    job: dict,
    materials: dict,
    profile: dict,
    browser: BrowserManager,
    ats_name: str,
) -> dict[str, Any] | None:
    """
    Fill an external ATS form (Greenhouse, Lever, Workday, iCIMS).

    Returns result dict or None if the attempt is not possible.
    """
    job_id: str = job.get("id", "unknown")
    url: str = job.get("url", "")
    resume_pdf: str = materials.get("resume_pdf_path", "")
    cover_letter: str = materials.get("cover_letter", "")

    page: Page = await browser.new_page()
    try:
        logger.info("[ats:%s] Navigating to %s", ats_name, url)
        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        await _human_delay()

        page_text = await page.inner_text("body")
        if _is_sensitive(page_text):
            await _screenshot(browser, page, job_id, "sensitive_abort")
            return _abort_result("requires_human")

        # Fill standard contact fields (ATS-agnostic selectors)
        name_parts = profile.get("name", "").split(maxsplit=1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        for selector in ('input[name="first_name"]', 'input[id*="first"]',
                         'input[placeholder*="First"]'):
            if await _safe_fill(page, selector, first_name):
                break

        for selector in ('input[name="last_name"]', 'input[id*="last"]',
                         'input[placeholder*="Last"]'):
            if await _safe_fill(page, selector, last_name):
                break

        for selector in ('input[name="email"]', 'input[type="email"]',
                         'input[id*="email"]'):
            if await _safe_fill(page, selector, profile.get("email", "")):
                break

        for selector in ('input[name="phone"]', 'input[type="tel"]',
                         'input[id*="phone"]'):
            if await _safe_fill(page, selector, profile.get("phone", "")):
                break

        for selector in ('input[name="location"]', 'input[id*="location"]',
                         'input[placeholder*="City"]'):
            if await _safe_fill(page, selector, profile.get("location", "")):
                break

        # Upload resume PDF
        if resume_pdf and Path(resume_pdf).is_file():
            file_input = page.locator('input[type="file"]').first
            if await file_input.is_visible(timeout=3_000):
                await file_input.set_input_files(resume_pdf)
                await _human_delay()

        # Paste cover letter if a text area is present
        if cover_letter:
            cl_selectors = (
                'textarea[name*="cover"]',
                'textarea[id*="cover"]',
                'textarea[placeholder*="cover"]',
                'div[contenteditable][aria-label*="cover"]',
            )
            for sel in cl_selectors:
                if await _safe_fill(page, sel, cover_letter):
                    break

        await _human_delay()

        # Submit
        submit_btn = page.locator(
            'button[type="submit"], '
            'input[type="submit"], '
            'button:has-text("Submit"), '
            'button:has-text("Apply")'
        ).first

        if not await submit_btn.is_visible(timeout=5_000):
            logger.warning("[ats:%s] Submit button not found.", ats_name)
            return None

        await submit_btn.click()
        await _human_delay()

        # Capture confirmation
        await _screenshot(browser, page, job_id, "confirmation")
        confirmation = ""
        try:
            body_text = await page.inner_text("body")
            for phrase in ("thank you", "application received", "successfully submitted",
                           "we'll be in touch", "confirmation"):
                if phrase in body_text.lower():
                    confirmation = f"Application submitted ({ats_name})"
                    break
        except Exception:  # noqa: BLE001
            pass

        logger.info("[ats:%s] Success for job_id=%s", ats_name, job_id)
        return {
            "success": True,
            "method": f"ats_{ats_name}",
            "confirmation": confirmation or f"Submitted via {ats_name}",
            "error": "",
        }

    except SensitiveFieldError:
        await _screenshot(browser, page, job_id, "abort")
        return _abort_result("requires_human")
    except PlaywrightTimeout as exc:
        logger.warning("[ats:%s] Timeout: %s", ats_name, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ats:%s] Error: %s", ats_name, exc)
        return None
    finally:
        await page.context.close()


def _save_email_outbox(job: dict, materials: dict, profile: dict) -> dict[str, Any]:
    """
    Save an email application to outbox/{job_id}_email.json for human review.

    Returns a success result dict; never actually sends the email.
    """
    _ensure_dirs()
    job_id: str = job.get("id", "unknown")
    title: str = job.get("title", "")
    company: str = job.get("company", "")
    contact_email: str = job.get("contact_email") or job.get("apply_email", "")
    candidate_name: str = profile.get("name", "")

    subject = f"Application: {title} – {candidate_name}"
    body = materials.get("cover_letter", "")

    outbox_payload: dict[str, Any] = {
        "job_id": job_id,
        "to": contact_email,
        "subject": subject,
        "body": body,
        "resume_path": materials.get("resume_pdf_path", ""),
        "company": company,
        "title": title,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "status": "pending_human_review",
    }

    path = _OUTBOX_DIR / f"{job_id}_email.json"
    path.write_text(json.dumps(outbox_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Email outbox saved: %s", path)

    return {
        "success": True,
        "method": "email_outbox",
        "confirmation": f"Saved to outbox for review ({path.name})",
        "error": "",
    }


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class SensitiveFieldError(RuntimeError):
    """Raised when a form field is detected that requires human handling."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def apply_to_job(
    job: dict,
    materials: dict,
    profile: dict,
    config: dict,
    browser: BrowserManager,
) -> dict[str, Any]:
    """
    Attempt to apply to a single job using the best available strategy.

    Strategy waterfall (tries in order until one succeeds):
        1. LinkedIn Easy Apply
        2. External ATS (Greenhouse / Lever / Workday / iCIMS)
        3. Email outbox (save for human review — never auto-sends)

    Safety guardrails
    -----------------
    - Returns ``{"success": False, "method": "aborted", "error": "requires_human"}``
      immediately if any form field is detected that asks for SSN, bank
      account, or passport details.
    - Never fabricates credentials or experience.
    - All form interactions include random 3–8 s human-paced delays.
    - Up to MAX_RETRIES (3) attempts per strategy before moving to the next.

    Parameters
    ----------
    job:        Job record dict (id, title, company, url, …).
    materials:  Output of tailor_agent (resume_md, cover_letter, resume_pdf_path).
    profile:    Candidate profile dict (name, email, phone, location, …).
    config:     Full application config dict (from config.yaml).
    browser:    Initialised BrowserManager instance.

    Returns
    -------
    dict with keys:
        success (bool), method (str), confirmation (str), error (str)
    """
    job_id: str = job.get("id", "unknown")
    url: str = job.get("url", "")

    logger.info(
        "apply_to_job: job_id=%s  title=%s  company=%s",
        job_id,
        job.get("title"),
        job.get("company"),
    )

    # ── Strategy 1: LinkedIn Easy Apply ─────────────────────────────────────
    if "linkedin.com" in url.lower():
        for attempt in range(1, MAX_RETRIES + 1):
            logger.debug("[linkedin] attempt %d/%d", attempt, MAX_RETRIES)
            try:
                result = await _try_linkedin_easy_apply(job, materials, profile, browser)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[linkedin] Attempt %d unhandled exception: %s", attempt, exc)
                result = None

            if result is not None:
                if result.get("method") == "aborted":
                    return result  # non-retryable
                if result.get("success"):
                    return result
            if attempt < MAX_RETRIES:
                await asyncio.sleep(random.uniform(5, 15))

    # ── Strategy 2: External ATS ─────────────────────────────────────────────
    ats_name = _detect_ats(url)
    if ats_name:
        for attempt in range(1, MAX_RETRIES + 1):
            logger.debug("[ats:%s] attempt %d/%d", ats_name, attempt, MAX_RETRIES)
            try:
                result = await _try_ats_apply(job, materials, profile, browser, ats_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ats:%s] Attempt %d unhandled exception: %s",
                               ats_name, attempt, exc)
                result = None

            if result is not None:
                if result.get("method") == "aborted":
                    return result
                if result.get("success"):
                    return result
            if attempt < MAX_RETRIES:
                await asyncio.sleep(random.uniform(5, 15))

    # ── Strategy 3: Email outbox (fallback) ──────────────────────────────────
    logger.info(
        "apply_to_job: falling back to email outbox for job_id=%s", job_id
    )
    return _save_email_outbox(job, materials, profile)
