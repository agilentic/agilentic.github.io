"""
main.py – Async orchestrator for the Job Application Agent.

CLI flags
---------
  --run        Run one full cycle immediately.
  --schedule   Run daily at 09:00 via APScheduler AsyncIOScheduler.
  --dry-run    Scrape + score only; no tailoring or applications.
  --dashboard  Launch the Streamlit dashboard in a subprocess and exit.
  --status     Print today's application summary to stdout and exit.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# ── Project modules ──────────────────────────────────────────────────────────
from agents.scraper_agent import scrape_all_platforms
from agents.scorer_agent import score_batch
from agents.tailor_agent import tailor_for_job
from agents.apply_agent import apply_to_job
from agents.tracker_agent import poll_responses, write_daily_digest
from db.database import init_db
from utils.browser import BrowserManager
from utils.rate_limiter import RateLimiter

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yaml"
DB_PATH_DEFAULT = ROOT / "db" / "jobs.db"
LOGS_DIR = ROOT / "logs"

# ── Logging setup ─────────────────────────────────────────────────────────────

def _setup_logging(run_timestamp: str) -> logging.Logger:
    """Configure root logger with both a rotating file handler and a console handler."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"run_{run_timestamp}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    return logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load config.yaml and merge environment-variable overrides."""
    load_dotenv()
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return cfg


def _within_application_hours(window: str) -> bool:
    """
    Return True if the current local time falls within *window*.

    *window* format: "HH:MM-HH:MM" (24-hour), e.g. "09:00-18:00".
    An empty or malformed window is treated as always open.
    """
    if not window:
        return True
    try:
        start_str, end_str = window.split("-", 1)
        now = datetime.now()
        start_h, start_m = map(int, start_str.strip().split(":"))
        end_h, end_m = map(int, end_str.strip().split(":"))
        start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        return start <= now <= end
    except Exception:  # noqa: BLE001
        return True


# ── Core cycle ────────────────────────────────────────────────────────────────

async def run_daily_cycle(dry_run: bool = False) -> None:
    """
    Execute one complete job-application cycle.

    Steps
    -----
    1.  Load config.yaml + .env
    2.  Init Database, BrowserManager, RateLimiter
    3.  Scrape all platforms → collect new jobs
    4.  Score all new jobs in batches of 10
    5.  Filter: keep score >= 0.65
    6.  Sort by score desc; cap at max_applications_per_day
    7.  Apply to each queued job (unless dry_run):
        a. tailor_agent
        b. apply_agent
        c. random sleep 45–120 s
        d. update DB
    8.  poll_responses()
    9.  write_daily_digest()
    """
    run_ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = _setup_logging(run_ts)

    logger.info("=" * 70)
    logger.info("Job Agent cycle starting  (dry_run=%s)", dry_run)
    logger.info("=" * 70)

    # ── 1. Config ──────────────────────────────────────────────────────────
    cfg = _load_config()
    preferences: dict = cfg.get("job_preferences", {})
    profile: dict = {**cfg.get("profile", {}), **preferences}
    email_config: dict = cfg.get("email", {})
    db_path: str = cfg.get("db_path", str(DB_PATH_DEFAULT))
    max_apps: int = preferences.get("max_applications_per_day", 25)
    app_window: str = preferences.get("application_hours", "09:00-18:00")
    score_threshold: float = float(cfg.get("score_threshold", 0.65))

    logger.info("Config loaded from %s", CONFIG_PATH)
    logger.info(
        "Preferences: max_apps=%d, window=%s, threshold=%.2f",
        max_apps, app_window, score_threshold,
    )

    # ── 2. Init infrastructure ─────────────────────────────────────────────
    db = await init_db(db_path)
    browser_cfg: dict = cfg.get("browser", {})
    headless: bool = os.environ.get("HEADLESS_BROWSER", "true").lower() != "false"
    browser = BrowserManager(headless=headless, **browser_cfg)
    limiter = RateLimiter(
        calls_per_minute=cfg.get("rate_limit_rpm", 10),
    )

    stats: dict = {
        "scraped": 0,
        "scored": 0,
        "queued": 0,
        "applied": 0,
        "failed": 0,
        "skipped_hours": 0,
    }

    try:
        # ── 3. Scrape ──────────────────────────────────────────────────────
        logger.info("--- SCRAPE PHASE ---")
        new_jobs: list[dict] = await scrape_all_platforms(preferences, db, limiter)
        stats["scraped"] = len(new_jobs)
        logger.info("Scraped %d new jobs", stats["scraped"])

        if not new_jobs:
            logger.info("No new jobs found; proceeding to tracker.")
        else:
            # ── 4. Score ───────────────────────────────────────────────────
            logger.info("--- SCORE PHASE ---")
            score_results: list[dict] = await score_batch(
                new_jobs, profile, batch_size=10
            )
            stats["scored"] = len(score_results)

            # Persist scores back to DB
            for job, result in zip(new_jobs, score_results):
                await db.update_job_status(
                    job["id"],
                    "scored",
                    relevance_score=result["score"],
                    domain=result.get("domain"),
                )

            # ── 5 & 6. Filter + sort + cap ─────────────────────────────────
            qualified: list[tuple[dict, dict]] = [
                (job, res)
                for job, res in zip(new_jobs, score_results)
                if res["score"] >= score_threshold
            ]
            qualified.sort(key=lambda pair: pair[1]["score"], reverse=True)
            qualified = qualified[:max_apps]
            stats["queued"] = len(qualified)

            logger.info(
                "Qualified (score >= %.2f): %d jobs queued (capped at %d)",
                score_threshold,
                stats["queued"],
                max_apps,
            )

            if dry_run:
                logger.info("DRY-RUN mode — skipping application phase.")
                for job, res in qualified:
                    logger.info(
                        "  [DRY-RUN] Would apply to: %s @ %s  score=%.2f",
                        job.get("title"),
                        job.get("company"),
                        res["score"],
                    )
            else:
                # ── 7. Apply ───────────────────────────────────────────────
                logger.info("--- APPLY PHASE ---")
                for job, scorer_output in qualified:
                    # 7a. DAILY_LIMIT guard
                    applied_today = await db.get_applications_today()
                    if applied_today >= max_apps:
                        logger.warning(
                            "Daily limit reached (%d/%d); stopping applications.",
                            applied_today, max_apps,
                        )
                        break

                    # 7b. Application hours guard
                    if not _within_application_hours(app_window):
                        stats["skipped_hours"] += 1
                        logger.info(
                            "Outside application hours (%s); skipping %s.",
                            app_window, job.get("title"),
                        )
                        continue

                    logger.info(
                        "Applying to: %s @ %s  (score=%.2f)",
                        job.get("title"),
                        job.get("company"),
                        scorer_output["score"],
                    )
                    await db.update_job_status(job["id"], "applying")

                    try:
                        # 7c. Tailor
                        materials: dict = await tailor_for_job(
                            job, scorer_output, profile
                        )

                        # 7d. Apply
                        apply_result: dict = await apply_to_job(
                            job, materials, profile, cfg, browser
                        )

                        if apply_result.get("success"):
                            await db.update_job_status(
                                job["id"],
                                "applied",
                                applied_at=datetime.now(tz=timezone.utc).isoformat(),
                            )
                            await db.insert_application(
                                {
                                    "job_id": job["id"],
                                    "resume_variant_path": materials.get("resume_path"),
                                    "cover_letter_text": materials.get("cover_letter"),
                                    "applied_via": apply_result.get("method"),
                                    "confirmation_text": apply_result.get("confirmation"),
                                }
                            )
                            stats["applied"] += 1
                            logger.info("  Applied successfully.")
                        else:
                            error_msg = apply_result.get("error", "unknown error")
                            await db.update_job_status(
                                job["id"], "skipped",
                            )
                            stats["failed"] += 1
                            logger.warning("  Application failed: %s", error_msg)

                    except Exception as exc:  # noqa: BLE001
                        logger.exception(
                            "Unhandled error applying to '%s': %s",
                            job.get("title"), exc,
                        )
                        await db.update_job_status(job["id"], "skipped")
                        stats["failed"] += 1

                    # 7e. Polite delay
                    delay = random.uniform(45, 120)
                    logger.debug("Sleeping %.0f s before next application.", delay)
                    await asyncio.sleep(delay)

        # ── 8. Poll email responses ────────────────────────────────────────
        logger.info("--- TRACKER PHASE ---")
        if email_config:
            try:
                await poll_responses(email_config, db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("poll_responses failed: %s", exc)
        else:
            logger.info("No email config; skipping poll_responses.")

        # ── 9. Daily digest ────────────────────────────────────────────────
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        try:
            await write_daily_digest(db, date_str)
            logger.info("Daily digest written for %s.", date_str)
        except Exception as exc:  # noqa: BLE001
            logger.warning("write_daily_digest failed: %s", exc)

    finally:
        await db.close()
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass

    # ── Summary ────────────────────────────────────────────────────────────
    logger.info("=" * 70)
    logger.info("Cycle complete.")
    logger.info(
        "  Scraped: %d  |  Scored: %d  |  Queued: %d  |  Applied: %d  |  "
        "Failed: %d  |  Skipped (hours): %d",
        stats["scraped"],
        stats["scored"],
        stats["queued"],
        stats["applied"],
        stats["failed"],
        stats["skipped_hours"],
    )
    logger.info("=" * 70)


# ── Status command ─────────────────────────────────────────────────────────────

async def _print_status() -> None:
    """Print today's application summary to stdout and exit."""
    load_dotenv()
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    db_path: str = cfg.get("db_path", str(DB_PATH_DEFAULT))

    db = await init_db(db_path)
    try:
        stats = await db.get_daily_stats()
        applied_today = await db.get_applications_today()
    finally:
        await db.close()

    print("\n=== Job Agent — Today's Summary ===")
    print(f"  Applications submitted today : {applied_today}")
    if stats:
        for status, count in sorted(stats.items()):
            print(f"  {status:<20}: {count}")
    else:
        print("  No activity recorded yet today.")
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-agent",
        description="Autonomous job application agent.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--run",
        action="store_true",
        help="Run one full cycle immediately.",
    )
    group.add_argument(
        "--schedule",
        action="store_true",
        help="Run daily at 09:00 via APScheduler (blocking).",
    )
    group.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the Streamlit analytics dashboard.",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Print today's summary and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Scrape and score only; do not submit applications.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.status:
        asyncio.run(_print_status())
        sys.exit(0)

    if args.dashboard:
        dashboard_path = ROOT / "dashboard" / "app.py"
        cmd = [
            sys.executable, "-m", "streamlit", "run",
            str(dashboard_path),
            "--server.port", "8501",
            "--server.address", "0.0.0.0",
        ]
        print(f"Launching dashboard: {' '.join(cmd)}")
        proc = subprocess.Popen(cmd)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
        sys.exit(proc.returncode or 0)

    if args.run:
        asyncio.run(run_daily_cycle(dry_run=args.dry_run))
        sys.exit(0)

    if args.schedule:
        # --dry-run is honoured when --schedule is used
        dry_run = args.dry_run

        scheduler = AsyncIOScheduler(timezone="America/Los_Angeles")
        scheduler.add_job(
            run_daily_cycle,
            trigger="cron",
            hour=9,
            minute=0,
            kwargs={"dry_run": dry_run},
            id="daily_cycle",
            name="Daily job application cycle",
            replace_existing=True,
        )

        async def _run_scheduler() -> None:
            scheduler.start()
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
            log = _setup_logging(ts)
            log.info("Scheduler started. Next run at 09:00 local time.")
            try:
                while True:
                    await asyncio.sleep(60)
            except (KeyboardInterrupt, SystemExit):
                log.info("Scheduler shutting down.")
                scheduler.shutdown(wait=False)

        asyncio.run(_run_scheduler())
        sys.exit(0)


if __name__ == "__main__":
    main()
