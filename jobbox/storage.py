"""SQLite storage for jobs, application statuses, saved flags and confirmations.

One database file per profile (data/jobbox_<profile>.db) so the two inboxes
stay fully separate. All writes are idempotent (keyed on dedup hashes), so
re-running ``sync`` never creates duplicates.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from .models import ApplicationStatus, Job


def _iso(d: Optional[dt.datetime]) -> Optional[str]:
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    dedup_key       TEXT PRIMARY KEY,
    company         TEXT,
    title           TEXT,
    location        TEXT,
    url             TEXT,
    source          TEXT,
    profile         TEXT,
    email_id        TEXT,
    posted_at       TEXT,
    received_at     TEXT,
    early_apply     INTEGER DEFAULT 0,
    match_score     INTEGER DEFAULT 0,
    matched_keywords TEXT,
    saved           INTEGER DEFAULT 0,
    first_seen      TEXT
);

CREATE TABLE IF NOT EXISTS statuses (
    key         TEXT PRIMARY KEY,
    company     TEXT,
    status      TEXT,
    profile     TEXT,
    email_id    TEXT,
    detected_at TEXT,
    subject     TEXT,
    confidence  TEXT DEFAULT 'auto'
);

CREATE INDEX IF NOT EXISTS idx_jobs_received ON jobs(received_at);
CREATE INDEX IF NOT EXISTS idx_jobs_saved ON jobs(saved);
CREATE INDEX IF NOT EXISTS idx_status_detected ON statuses(detected_at);
"""


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- Jobs ---------------------------------------------------------------
    def upsert_job(self, job: Job) -> bool:
        """Insert a job if new; refresh volatile fields if seen. Returns True if new."""
        key = job.dedup_key()
        now = _iso(dt.datetime.now(tz=dt.timezone.utc))
        cur = self.conn.execute("SELECT dedup_key FROM jobs WHERE dedup_key = ?", (key,))
        exists = cur.fetchone() is not None

        if exists:
            self.conn.execute(
                """UPDATE jobs SET early_apply=?, match_score=?, matched_keywords=?
                   WHERE dedup_key=?""",
                (int(job.early_apply), job.match_score, job.matched_keywords, key),
            )
        else:
            self.conn.execute(
                """INSERT INTO jobs (dedup_key, company, title, location, url, source,
                        profile, email_id, posted_at, received_at, early_apply,
                        match_score, matched_keywords, saved, first_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
                (
                    key, job.company, job.title, job.location, job.url, job.source,
                    job.profile, job.email_id, _iso(job.posted_at), _iso(job.received_at),
                    int(job.early_apply), job.match_score, job.matched_keywords, now,
                ),
            )
        self.conn.commit()
        return not exists

    def set_saved(self, dedup_key: str, saved: bool) -> None:
        self.conn.execute("UPDATE jobs SET saved=? WHERE dedup_key=?", (int(saved), dedup_key))
        self.conn.commit()

    def get_jobs(self, saved_only: bool = False, order: str = "received") -> List[dict]:
        q = "SELECT * FROM jobs"
        if saved_only:
            q += " WHERE saved = 1"
        if order == "score":
            q += " ORDER BY match_score DESC, received_at DESC"
        else:
            q += " ORDER BY received_at DESC, match_score DESC"
        return [dict(r) for r in self.conn.execute(q).fetchall()]

    # -- Statuses -----------------------------------------------------------
    def upsert_status(self, status: ApplicationStatus) -> bool:
        key = status.key()
        cur = self.conn.execute("SELECT key FROM statuses WHERE key = ?", (key,))
        if cur.fetchone() is not None:
            return False
        self.conn.execute(
            """INSERT INTO statuses (key, company, status, profile, email_id,
                    detected_at, subject, confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                key, status.company, status.status, status.profile, status.email_id,
                _iso(status.detected_at), status.subject, status.confidence,
            ),
        )
        self.conn.commit()
        return True

    def set_status_confidence(self, key: str, confidence: str) -> None:
        self.conn.execute("UPDATE statuses SET confidence=? WHERE key=?", (confidence, key))
        self.conn.commit()

    def get_statuses(self, include_rejected_by_user: bool = False) -> List[dict]:
        q = "SELECT * FROM statuses"
        if not include_rejected_by_user:
            q += " WHERE confidence != 'rejected_by_user'"
        q += " ORDER BY detected_at DESC"
        return [dict(r) for r in self.conn.execute(q).fetchall()]

    # -- Stats for Insights -------------------------------------------------
    def applications_per_week(self) -> List[Dict[str, int]]:
        """Count 'Applied' statuses grouped by ISO week."""
        rows = self.conn.execute(
            "SELECT detected_at FROM statuses WHERE status='Applied' "
            "AND confidence != 'rejected_by_user'"
        ).fetchall()
        buckets: Dict[str, int] = {}
        for r in rows:
            d = _parse_iso(r["detected_at"])
            if not d:
                continue
            year, week, _ = d.isocalendar()
            label = f"{year}-W{week:02d}"
            buckets[label] = buckets.get(label, 0) + 1
        return [{"week": k, "count": v} for k, v in sorted(buckets.items())]

    def status_counts(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM statuses "
            "WHERE confidence != 'rejected_by_user' GROUP BY status"
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    def response_rate(self) -> float:
        """Interviews+Rejections as a fraction of Applied (0-100)."""
        counts = self.status_counts()
        applied = counts.get("Applied", 0)
        responded = counts.get("Interview", 0) + counts.get("Rejected", 0)
        if applied == 0:
            return 0.0
        return round(min(100.0, responded / applied * 100.0), 1)

    def summary(self) -> Dict[str, int]:
        total_jobs = self.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        saved = self.conn.execute("SELECT COUNT(*) c FROM jobs WHERE saved=1").fetchone()["c"]
        early = self.conn.execute("SELECT COUNT(*) c FROM jobs WHERE early_apply=1").fetchone()["c"]
        return {"total_jobs": total_jobs, "saved": saved, "early_apply": early}
