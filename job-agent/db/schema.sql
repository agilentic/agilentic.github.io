-- Job Application Agent – SQLite Schema
-- Run once via db/database.py:init_db()

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- jobs
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,          -- e.g. sha256(url)[:16]
    title            TEXT NOT NULL,
    company          TEXT NOT NULL,
    url              TEXT NOT NULL UNIQUE,
    platform         TEXT NOT NULL,             -- 'linkedin','indeed','lever',etc.
    domain           TEXT,                      -- matched domain from config
    job_type         TEXT,                      -- 'full-time','contract',…
    salary_text      TEXT,                      -- raw salary string from listing
    description      TEXT,                      -- full JD text
    relevance_score  REAL DEFAULT 0.0,          -- 0.0–1.0 from LLM scorer
    status           TEXT NOT NULL DEFAULT 'new',
        -- new | scored | applying | applied | rejected | interview | offer | skipped
    discovered_at    TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    applied_at       TIMESTAMP,
    last_updated     TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ─────────────────────────────────────────────────────────────
-- applications
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS applications (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id               TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    resume_variant_path  TEXT,                  -- path to PDF used
    cover_letter_text    TEXT,                  -- generated cover letter
    applied_via          TEXT,                  -- 'easy_apply','direct','email',…
    confirmation_text    TEXT,                  -- confirmation message / ATS ID
    applied_at           TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ─────────────────────────────────────────────────────────────
-- responses  (emails / portal messages received back)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS responses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    received_at    TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    response_type  TEXT,   -- 'rejection','interview','offer','other'
    raw_email      TEXT    -- full RFC-2822 text for audit
);

-- ─────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────

-- Fast pipeline queries – fetch by status
CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs(status);

-- Dashboard / reporting – filter by domain
CREATE INDEX IF NOT EXISTS idx_jobs_domain
    ON jobs(domain);

-- Per-platform rate-limit checks & stats
CREATE INDEX IF NOT EXISTS idx_jobs_platform
    ON jobs(platform);

-- Daily limit guard – count applied_at for today
CREATE INDEX IF NOT EXISTS idx_jobs_applied_at
    ON jobs(applied_at);

-- Join from applications → jobs
CREATE INDEX IF NOT EXISTS idx_applications_job_id
    ON applications(job_id);

-- Recent-application queries
CREATE INDEX IF NOT EXISTS idx_applications_applied_at
    ON applications(applied_at);

-- Inbox-polling deduplication
CREATE INDEX IF NOT EXISTS idx_responses_job_id
    ON responses(job_id);

CREATE INDEX IF NOT EXISTS idx_responses_received_at
    ON responses(received_at);
