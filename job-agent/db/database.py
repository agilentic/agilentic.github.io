"""
db/database.py – Async SQLite access layer using aiosqlite.

All public methods are safe to call concurrently; a single aiosqlite
connection is shared and serialised internally by aiosqlite's own lock.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _row_to_dict(cursor: aiosqlite.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    """Convert an aiosqlite Row to a plain dict."""
    return {col[0]: row[col[0]] for col in cursor.description}


class Database:
    """
    Async SQLite wrapper.

    Usage::

        async with Database(db_path) as db:
            await db.insert_job(job_dict)

    Or acquire via the module-level factory::

        db = await init_db("jobs.db")
        ...
        await db.close()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------ #
    # Context-manager support
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "Database":
        await self._open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def _open(self) -> None:
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row  # type: ignore[assignment]
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA foreign_keys = ON")

    async def close(self) -> None:
        """Close the underlying connection (idempotent)."""
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error closing DB connection: %s", exc)
            finally:
                self._conn = None

    # ------------------------------------------------------------------ #
    # Schema bootstrap
    # ------------------------------------------------------------------ #

    async def _apply_schema(self) -> None:
        """Execute schema.sql (CREATE TABLE IF NOT EXISTS …)."""
        sql = _SCHEMA_PATH.read_text()
        await self._conn.executescript(sql)  # type: ignore[union-attr]
        await self._conn.commit()  # type: ignore[union-attr]

    # ------------------------------------------------------------------ #
    # jobs table
    # ------------------------------------------------------------------ #

    async def insert_job(self, job: dict[str, Any]) -> bool:
        """
        INSERT OR IGNORE a job row.

        Returns True when the row was newly inserted, False when it already
        existed (url collision).
        """
        sql = """
            INSERT OR IGNORE INTO jobs
                (id, title, company, url, platform, domain, job_type,
                 salary_text, description, relevance_score, status,
                 discovered_at, applied_at, last_updated)
            VALUES
                (:id, :title, :company, :url, :platform, :domain, :job_type,
                 :salary_text, :description, :relevance_score, :status,
                 :discovered_at, :applied_at, :last_updated)
        """
        defaults: dict[str, Any] = {
            "domain": None,
            "job_type": None,
            "salary_text": None,
            "description": None,
            "relevance_score": 0.0,
            "status": "new",
            "discovered_at": _now_iso(),
            "applied_at": None,
            "last_updated": _now_iso(),
        }
        row = {**defaults, **job}
        try:
            async with self._conn.execute(sql, row) as cur:  # type: ignore[union-attr]
                inserted = cur.rowcount == 1
            await self._conn.commit()  # type: ignore[union-attr]
            return inserted
        except Exception as exc:
            logger.error("insert_job failed for job_id=%s: %s", job.get("id"), exc)
            return False

    async def update_job_status(
        self,
        job_id: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        """
        Update a job's status and any additional columns supplied via kwargs.

        Example::

            await db.update_job_status("abc123", "applied",
                                       applied_at=datetime.now(tz=timezone.utc).isoformat(),
                                       relevance_score=0.87)
        """
        allowed_columns = {
            "title", "company", "url", "platform", "domain", "job_type",
            "salary_text", "description", "relevance_score", "applied_at",
        }
        updates: dict[str, Any] = {"status": status, "last_updated": _now_iso()}
        for k, v in kwargs.items():
            if k in allowed_columns:
                updates[k] = v
            else:
                logger.warning("update_job_status: ignoring unknown column '%s'", k)

        set_clause = ", ".join(f"{col} = :{col}" for col in updates)
        sql = f"UPDATE jobs SET {set_clause} WHERE id = :job_id"
        params = {**updates, "job_id": job_id}
        try:
            await self._conn.execute(sql, params)  # type: ignore[union-attr]
            await self._conn.commit()  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("update_job_status failed for job_id=%s: %s", job_id, exc)

    async def get_jobs_by_status(self, status: str) -> list[dict[str, Any]]:
        """Return all jobs matching *status*, ordered by discovered_at DESC."""
        sql = "SELECT * FROM jobs WHERE status = ? ORDER BY discovered_at DESC"
        try:
            async with self._conn.execute(sql, (status,)) as cur:  # type: ignore[union-attr]
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_jobs_by_status(%s) failed: %s", status, exc)
            return []

    async def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Return a single job dict or None if not found."""
        sql = "SELECT * FROM jobs WHERE id = ?"
        try:
            async with self._conn.execute(sql, (job_id,)) as cur:  # type: ignore[union-attr]
                row = await cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error("get_job(%s) failed: %s", job_id, exc)
            return None

    # ------------------------------------------------------------------ #
    # applications table
    # ------------------------------------------------------------------ #

    async def insert_application(self, app: dict[str, Any]) -> None:
        """
        Record a submitted application.

        Required keys: job_id
        Optional keys: resume_variant_path, cover_letter_text,
                       applied_via, confirmation_text, applied_at
        """
        sql = """
            INSERT INTO applications
                (job_id, resume_variant_path, cover_letter_text,
                 applied_via, confirmation_text, applied_at)
            VALUES
                (:job_id, :resume_variant_path, :cover_letter_text,
                 :applied_via, :confirmation_text, :applied_at)
        """
        defaults: dict[str, Any] = {
            "resume_variant_path": None,
            "cover_letter_text": None,
            "applied_via": None,
            "confirmation_text": None,
            "applied_at": _now_iso(),
        }
        row = {**defaults, **app}
        try:
            await self._conn.execute(sql, row)  # type: ignore[union-attr]
            await self._conn.commit()  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("insert_application failed for job_id=%s: %s", app.get("job_id"), exc)

    # ------------------------------------------------------------------ #
    # responses table
    # ------------------------------------------------------------------ #

    async def insert_response(self, resp: dict[str, Any]) -> None:
        """
        Record an inbound email / portal message.

        Optional keys: job_id, response_type, raw_email, received_at
        """
        sql = """
            INSERT INTO responses
                (job_id, received_at, response_type, raw_email)
            VALUES
                (:job_id, :received_at, :response_type, :raw_email)
        """
        defaults: dict[str, Any] = {
            "job_id": None,
            "received_at": _now_iso(),
            "response_type": "other",
            "raw_email": None,
        }
        row = {**defaults, **resp}
        try:
            await self._conn.execute(sql, row)  # type: ignore[union-attr]
            await self._conn.commit()  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("insert_response failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Analytics helpers
    # ------------------------------------------------------------------ #

    async def get_daily_stats(self) -> dict[str, int]:
        """
        Return status counts for jobs whose last_updated is today (UTC).

        Example return value::

            {"new": 12, "applied": 5, "interview": 1, "rejected": 3, ...}
        """
        sql = """
            SELECT status, COUNT(*) AS cnt
            FROM jobs
            WHERE date(last_updated) = date('now')
            GROUP BY status
        """
        try:
            async with self._conn.execute(sql) as cur:  # type: ignore[union-attr]
                rows = await cur.fetchall()
                return {row["status"]: row["cnt"] for row in rows}
        except Exception as exc:
            logger.error("get_daily_stats failed: %s", exc)
            return {}

    async def get_applications_today(self) -> int:
        """
        Count applications submitted today (UTC).

        Used by the daily-limit guard before each application attempt.
        """
        sql = """
            SELECT COUNT(*) AS cnt
            FROM applications
            WHERE date(applied_at) = date('now')
        """
        try:
            async with self._conn.execute(sql) as cur:  # type: ignore[union-attr]
                row = await cur.fetchone()
                return int(row["cnt"]) if row else 0
        except Exception as exc:
            logger.error("get_applications_today failed: %s", exc)
            return 0


# ------------------------------------------------------------------ #
# Module-level factory
# ------------------------------------------------------------------ #

async def init_db(db_path: str) -> Database:
    """
    Create (or open) the SQLite database at *db_path*, run schema.sql,
    and return a ready-to-use :class:`Database` instance.
    """
    db = Database(db_path)
    await db._open()
    await db._apply_schema()
    logger.info("Database ready at %s", os.path.abspath(db_path))
    return db


# ------------------------------------------------------------------ #
# Private helpers
# ------------------------------------------------------------------ #

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
