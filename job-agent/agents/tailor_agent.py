"""
tailor_agent.py
---------------
Tailors a resume and generates a cover letter for a specific job,
then converts the resume to PDF via pandoc.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

from utils.llm import chat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROFILE_DIR = Path(__file__).resolve().parent.parent / "profile"
_RESUME_BASE_PATH = _PROFILE_DIR / "resume_base.md"
_VARIANTS_DIR = _PROFILE_DIR / "variants"

# ---------------------------------------------------------------------------
# System prompts (verbatim from spec)
# ---------------------------------------------------------------------------

_RESUME_SYSTEM = (
    "Rewrite the Skills and Experience bullet points to naturally incorporate these "
    "ATS keywords without fabricating experience. Preserve all dates, institutions, "
    "and factual content. Output only the updated Markdown resume."
)

_COVER_LETTER_SYSTEM = (
    "You are a professional cover letter writer. Write a 3-paragraph cover letter "
    "(max 280 words). Paragraph 1: Hook — why this specific company/role excites the "
    "candidate. Paragraph 2: Strongest 2 relevant experiences with measurable impact. "
    "Paragraph 3: Forward-looking close. Confident, not sycophantic. Tone: "
    "domain-appropriate (quant=precise, AI=curious, real_estate=analytical, "
    "tutoring=warm). No generic phrases like 'I am excited to apply.' "
    "Output plain text only."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_resume_base() -> str:
    """Load base resume Markdown; raise FileNotFoundError with a clear message."""
    if not _RESUME_BASE_PATH.exists():
        raise FileNotFoundError(
            f"Base resume not found at {_RESUME_BASE_PATH}. "
            "Please create profile/resume_base.md before running the tailor agent."
        )
    return _RESUME_BASE_PATH.read_text(encoding="utf-8")


def _ensure_variants_dir() -> Path:
    _VARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    return _VARIANTS_DIR


def _save_markdown(job_id: str, content: str) -> Path:
    variants = _ensure_variants_dir()
    md_path = variants / f"{job_id}_resume.md"
    md_path.write_text(content, encoding="utf-8")
    logger.debug("Saved tailored resume MD to %s", md_path)
    return md_path


async def _convert_to_pdf(md_path: Path, pdf_path: Path) -> bool:
    """
    Convert a Markdown file to PDF using pandoc (run in executor to avoid blocking).
    Returns True on success, False if pandoc is unavailable or conversion fails.
    """
    loop = asyncio.get_event_loop()

    def _run() -> bool:
        try:
            result = subprocess.run(
                [
                    "pandoc",
                    str(md_path),
                    "-o", str(pdf_path),
                    "--pdf-engine=xelatex",
                    "-V", "geometry:margin=1in",
                    "-V", "fontsize=11pt",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.warning(
                    "pandoc exited %d for %s: %s",
                    result.returncode,
                    md_path.name,
                    result.stderr.strip(),
                )
                return False
            return True
        except FileNotFoundError:
            logger.warning(
                "pandoc not found on PATH — PDF conversion skipped for %s", md_path.name
            )
            return False
        except subprocess.TimeoutExpired:
            logger.warning("pandoc timed out converting %s", md_path.name)
            return False

    return await loop.run_in_executor(None, _run)


def _build_cover_letter_user_prompt(
    job: dict,
    scorer_output: dict,
    profile: dict,
) -> str:
    """Construct the user message for cover letter generation."""
    return (
        f"Candidate Name: {profile.get('name', '[Your Name]')}\n"
        f"Target Role: {job.get('title', 'N/A')}\n"
        f"Company: {job.get('company', 'N/A')}\n"
        f"Domain: {scorer_output.get('domain', 'other')}\n"
        f"Reasoning (why good fit): {scorer_output.get('reasoning', '')}\n"
        f"ATS Keywords to weave in naturally: "
        f"{json.dumps(scorer_output.get('ats_keywords', []))}\n\n"
        f"Job Description:\n{job.get('description', 'No description provided.')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def tailor_for_job(
    job: dict,
    scorer_output: dict,
    profile: dict,
) -> dict:
    """
    Tailor resume and generate cover letter for a specific job.

    Args:
        job:            Job record dict (must include 'id', 'title', 'company',
                        'description').
        scorer_output:  Output from scorer_agent.score_job (must include
                        'ats_keywords', 'domain', 'reasoning').
        profile:        Candidate profile dict (name, email, etc.).

    Returns:
        {
            "resume_md":       str  — tailored resume in Markdown,
            "cover_letter":    str  — plain-text cover letter,
            "resume_pdf_path": str  — absolute path to PDF (or MD path if pandoc
                                      unavailable),
        }
    """
    job_id: str = job.get("id") or job.get("url", "unknown")

    # ── 1. Load base resume ───────────────────────────────────────────────
    resume_base = _load_resume_base()

    # ── 2. Tailor resume via Claude (concurrently with cover letter below) ─
    ats_keywords = scorer_output.get("ats_keywords", [])
    resume_user_prompt = (
        f"Keywords: {json.dumps(ats_keywords)}\n\nResume:\n{resume_base}"
    )

    cover_letter_user_prompt = _build_cover_letter_user_prompt(job, scorer_output, profile)

    logger.info(
        "Tailoring resume and cover letter for job '%s' (id=%s)",
        job.get("title"),
        job_id,
    )

    resume_md_task = asyncio.create_task(
        chat(_RESUME_SYSTEM, resume_user_prompt), name="tailor_resume"
    )
    cover_letter_task = asyncio.create_task(
        chat(_COVER_LETTER_SYSTEM, cover_letter_user_prompt), name="cover_letter"
    )

    resume_md, cover_letter = await asyncio.gather(resume_md_task, cover_letter_task)

    resume_md = resume_md.strip()
    cover_letter = cover_letter.strip()

    # ── 3 & 4. Save tailored resume MD ────────────────────────────────────
    md_path = _save_markdown(job_id, resume_md)

    # ── 5 & 6. Convert to PDF ─────────────────────────────────────────────
    variants = _ensure_variants_dir()
    pdf_path = variants / f"{job_id}_resume.pdf"

    pdf_success = await _convert_to_pdf(md_path, pdf_path)

    if pdf_success:
        resume_pdf_path = str(pdf_path)
        logger.info("PDF saved to %s", resume_pdf_path)
    else:
        # Fallback: point callers at the Markdown file
        resume_pdf_path = str(md_path)
        logger.warning(
            "PDF conversion unavailable; using MD path as resume_pdf_path: %s",
            resume_pdf_path,
        )

    # ── 7. Return ──────────────────────────────────────────────────────────
    return {
        "resume_md": resume_md,
        "cover_letter": cover_letter,
        "resume_pdf_path": resume_pdf_path,
    }
