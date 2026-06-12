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


def create_job(job_id: str, filename: str):
    now = time.time()
    with _conn() as c:
        c.execute("INSERT INTO jobs (id, filename, status, stage, created_at, updated_at) "
                  "VALUES (?, ?, 'queued', 'queued', ?, ?)", (job_id, filename, now, now))


def update_stage(job_id: str, stage: str, message: str = ""):
    with _conn() as c:
        c.execute("UPDATE jobs SET status='processing', stage=?, message=?, updated_at=? WHERE id=?",
                  (stage, message, time.time(), job_id))


def set_done(job_id: str, result: dict):
    with _conn() as c:
        c.execute("UPDATE jobs SET status='done', stage='done', message='', result=?, updated_at=? WHERE id=?",
                  (json.dumps(result), time.time(), job_id))


def set_error(job_id: str, error: str):
    with _conn() as c:
        c.execute("UPDATE jobs SET status='error', error=?, updated_at=? WHERE id=?",
                  (error[:500], time.time(), job_id))


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
