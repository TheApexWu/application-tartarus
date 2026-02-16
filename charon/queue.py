"""
Job queue backed by SQLite. Tracks jobs from scraping through submission.

Statuses:
  scraped   - Found by scraper, awaiting review
  approved  - User approved for auto-apply
  skipped   - User rejected
  tailoring - Resume being generated
  ready     - Resume generated, ready to submit
  filling   - Form being filled
  submitted - Application submitted
  failed    - Submission failed (error logged)
  manual    - Needs manual intervention
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from .config import DB_FILE


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_FILE))
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            platform TEXT,
            jd_text TEXT,
            profile TEXT,
            status TEXT DEFAULT 'scraped',
            resume_path TEXT,
            error TEXT,
            source TEXT,
            scraped_at TEXT,
            submitted_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS form_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER REFERENCES jobs(id),
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            source TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    return db


def add_job(company: str, role: str, url: str, platform: str = None,
            jd_text: str = None, source: str = "manual") -> int:
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO jobs (company, role, url, platform, jd_text, source, scraped_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (company, role, url, platform, jd_text, source, datetime.now().isoformat())
        )
        db.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        # URL already exists
        row = db.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
        return row["id"] if row else -1


def update_status(job_id: int, status: str, error: str = None, resume_path: str = None):
    db = get_db()
    fields = ["status = ?", "updated_at = ?"]
    values = [status, datetime.now().isoformat()]
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if resume_path is not None:
        fields.append("resume_path = ?")
        values.append(resume_path)
    if status == "submitted":
        fields.append("submitted_at = ?")
        values.append(datetime.now().isoformat())
    values.append(job_id)
    db.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()


def get_jobs(status: str = None) -> list:
    db = get_db()
    if status:
        rows = db.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_job(job_id: int) -> dict:
    db = get_db()
    row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def stats() -> dict:
    db = get_db()
    rows = db.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status").fetchall()
    return {r["status"]: r["cnt"] for r in rows}
