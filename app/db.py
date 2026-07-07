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

-- Schools platform (TASK-026 P0). Students join with a code, so no student
-- email is required (COPPA-friendly usernames).
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  pass_hash TEXT NOT NULL,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS schools (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  student_code TEXT UNIQUE NOT NULL,
  coach_code TEXT UNIQUE NOT NULL,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS memberships (
  user_id TEXT NOT NULL,
  school_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin', 'coach', 'student')),
  created_at REAL,
  PRIMARY KEY (user_id, school_id)
);
CREATE TABLE IF NOT EXISTS auth_sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at REAL,
  expires_at REAL
);
-- A job (session video) assigned to a student, optionally pinning WHICH tracked
-- player (P1/P2 id from players_track) is that student.
CREATE TABLE IF NOT EXISTS job_students (
  job_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  player_id INTEGER,
  assigned_by TEXT,
  created_at REAL,
  PRIMARY KEY (job_id, student_id)
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
        # TASK-026: job ownership (anonymous jobs keep NULLs; scoped views filter).
        if "school_id" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN school_id TEXT")
        if "uploaded_by" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN uploaded_by TEXT")


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


def recent_jobs(limit: int = 60) -> list[dict]:
    """All jobs (any status) newest-first, for the queue view (TASK-005)."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------- schools (TASK-026)

def create_user(user_id: str, username: str, name: str, pass_hash: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO users (id, username, name, pass_hash, created_at) "
                  "VALUES (?, ?, ?, ?, ?)",
                  (user_id, username.lower().strip(), name.strip(), pass_hash, time.time()))


def get_user_by_username(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?",
                        (username.lower().strip(),)).fetchone()
    return dict(row) if row else None


def get_user(user_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_school(school_id: str, name: str, student_code: str, coach_code: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO schools (id, name, student_code, coach_code, created_at) "
                  "VALUES (?, ?, ?, ?, ?)",
                  (school_id, name.strip(), student_code, coach_code, time.time()))


def get_school(school_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
    return dict(row) if row else None


def school_by_join_code(code: str) -> tuple[dict, str] | None:
    """Resolve a join code to (school, role). Codes are single-purpose."""
    code = code.strip().upper()
    with _conn() as c:
        row = c.execute("SELECT * FROM schools WHERE student_code=?", (code,)).fetchone()
        if row:
            return dict(row), "student"
        row = c.execute("SELECT * FROM schools WHERE coach_code=?", (code,)).fetchone()
        if row:
            return dict(row), "coach"
    return None


def add_membership(user_id: str, school_id: str, role: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO memberships (user_id, school_id, role, created_at) "
                  "VALUES (?, ?, ?, ?)", (user_id, school_id, role, time.time()))


def membership_of(user_id: str) -> dict | None:
    """The user's school membership (P0: one school per user — first wins)."""
    with _conn() as c:
        row = c.execute(
            "SELECT m.school_id, m.role, s.name AS school_name "
            "FROM memberships m JOIN schools s ON s.id = m.school_id "
            "WHERE m.user_id=? ORDER BY m.created_at LIMIT 1", (user_id,)).fetchone()
    return dict(row) if row else None


def school_members(school_id: str, role: str | None = None) -> list[dict]:
    q = ("SELECT u.id, u.username, u.name, m.role, m.created_at "
         "FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.school_id=?")
    args: list = [school_id]
    if role:
        q += " AND m.role=?"
        args.append(role)
    with _conn() as c:
        rows = c.execute(q + " ORDER BY u.name", args).fetchall()
    return [dict(r) for r in rows]


def create_auth_session(token: str, user_id: str, ttl_sec: float) -> None:
    now = time.time()
    with _conn() as c:
        c.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
        c.execute("INSERT INTO auth_sessions (token, user_id, created_at, expires_at) "
                  "VALUES (?, ?, ?, ?)", (token, user_id, now, now + ttl_sec))


def auth_session_user(token: str) -> dict | None:
    if not token:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT u.* FROM auth_sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token=? AND s.expires_at > ?", (token, time.time())).fetchone()
    return dict(row) if row else None


def delete_auth_session(token: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM auth_sessions WHERE token=?", (token,))


def set_job_owner(job_id: str, school_id: str | None, user_id: str | None) -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET school_id=?, uploaded_by=?, updated_at=? WHERE id=?",
                  (school_id, user_id, time.time(), job_id))


def school_jobs(school_id: str, limit: int = 120) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM jobs WHERE school_id=? "
                         "ORDER BY created_at DESC LIMIT ?", (school_id, limit)).fetchall()
    return [dict(r) for r in rows]


def assign_job_student(job_id: str, student_id: str, player_id: int | None,
                       assigned_by: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO job_students "
                  "(job_id, student_id, player_id, assigned_by, created_at) "
                  "VALUES (?, ?, ?, ?, ?)",
                  (job_id, student_id, player_id, assigned_by, time.time()))


def unassign_job_student(job_id: str, student_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM job_students WHERE job_id=? AND student_id=?",
                  (job_id, student_id))


def student_assignments(student_id: str) -> list[dict]:
    """The student's assigned jobs (done only), newest first, with player pins."""
    with _conn() as c:
        rows = c.execute(
            "SELECT j.*, a.player_id, a.created_at AS assigned_at "
            "FROM job_students a JOIN jobs j ON j.id = a.job_id "
            "WHERE a.student_id=? AND j.status='done' "
            "ORDER BY j.created_at DESC", (student_id,)).fetchall()
    return [dict(r) for r in rows]


def job_assignees(job_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT u.id, u.name, a.player_id FROM job_students a "
            "JOIN users u ON u.id = a.student_id WHERE a.job_id=?", (job_id,)).fetchall()
    return [dict(r) for r in rows]
