"""SQLite job store (stdlib sqlite3, WAL mode, one connection per call — simple and safe)."""
import json
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  filename TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  stage TEXT DEFAULT 'queued',
  message TEXT DEFAULT '',
  result TEXT,
  error TEXT,
  options TEXT,
  pipeline TEXT DEFAULT 'unknown',
  started_at REAL,
  finished_at REAL,
  created_at REAL,
  updated_at REAL
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with _conn() as c:
        c.executescript(SCHEMA)
        # Migration for DBs created before per-job options existed.
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
        if "options" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN options TEXT")
        if "pipeline" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN pipeline TEXT DEFAULT 'unknown'")
        if "started_at" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN started_at REAL")
        if "finished_at" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN finished_at REAL")
        c.execute("UPDATE jobs SET status='failed' WHERE status='error'")
        c.execute("UPDATE jobs SET pipeline=CASE "
                  "WHEN options LIKE '%tracknetv3%' THEN 'gpu' ELSE 'cpu' END "
                  "WHERE pipeline IS NULL OR pipeline='' OR pipeline='unknown'")
        c.execute("UPDATE jobs SET started_at=created_at "
                  "WHERE started_at IS NULL AND created_at IS NOT NULL "
                  "AND status IN ('processing', 'done', 'failed')")
        c.execute("UPDATE jobs SET finished_at=updated_at "
                  "WHERE finished_at IS NULL AND updated_at IS NOT NULL "
                  "AND status IN ('done', 'failed')")


def create_job(job_id: str, filename: str, options: dict | None = None):
    now = time.time()
    opt = options or {}
    pipeline = config.pipeline_for_options(opt)
    with _conn() as c:
        c.execute("INSERT INTO jobs (id, filename, status, stage, options, pipeline, "
                  "created_at, updated_at) "
                  "VALUES (?, ?, 'queued', 'queued', ?, ?, ?, ?)",
                  (job_id, filename, json.dumps(opt), pipeline, now, now))


def job_options(job_id: str) -> dict:
    job = get_job(job_id)
    if not job or not job.get("options"):
        return {}
    try:
        return json.loads(job["options"])
    except (ValueError, TypeError):
        return {}


def update_stage(job_id: str, stage: str, message: str = ""):
    now = time.time()
    with _conn() as c:
        c.execute("UPDATE jobs SET status='processing', stage=?, message=?, "
                  "started_at=COALESCE(started_at, ?), finished_at=NULL, updated_at=? "
                  "WHERE id=?",
                  (stage, message, now, now, job_id))


def set_pipeline(job_id: str, pipeline: str):
    if pipeline not in {"cpu", "gpu", "unknown"}:
        pipeline = "unknown"
    with _conn() as c:
        c.execute("UPDATE jobs SET pipeline=?, updated_at=? WHERE id=?",
                  (pipeline, time.time(), job_id))


def set_done(job_id: str, result: dict):
    now = time.time()
    with _conn() as c:
        c.execute("UPDATE jobs SET status='done', stage='done', message='', result=?, "
                  "started_at=COALESCE(started_at, ?), finished_at=?, updated_at=? "
                  "WHERE id=?",
                  (json.dumps(result), now, now, now, job_id))


def set_error(job_id: str, error: str):
    now = time.time()
    with _conn() as c:
        c.execute("UPDATE jobs SET status='failed', error=?, "
                  "started_at=COALESCE(started_at, ?), finished_at=?, updated_at=? "
                  "WHERE id=?",
                  (error[:500], now, now, now, job_id))


def get_job(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def pending_jobs() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT id FROM jobs WHERE status IN ('queued','processing') "
                         "ORDER BY created_at").fetchall()
    return [r["id"] for r in rows]


def gallery(limit: int = 60) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM jobs WHERE status='done' ORDER BY updated_at DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]
