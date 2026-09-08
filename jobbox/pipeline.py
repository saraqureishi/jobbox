"""The sync pipeline: Gmail -> parse -> enrich -> detect status -> store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .config import ProfileConfig
from .gmail_client import EmailMessage, GmailClient
from .parsers import parse_email
from .scoring import process_jobs
from .status_detect import detect_statuses
from .storage import Storage


@dataclass
class SyncResult:
    profile: str
    emails_read: int
    jobs_found: int
    jobs_new: int
    statuses_found: int
    statuses_new: int


def sync_profile(
    cfg: ProfileConfig,
    max_results: int = 500,
    emails: Optional[List[EmailMessage]] = None,
) -> SyncResult:
    """Run one full sync for a profile.

    If ``emails`` is provided (e.g. from fixtures or ``--demo``), Gmail is not
    contacted — handy for testing and for the seed-data demo.
    """
    if emails is None:
        client = GmailClient(cfg.resolved_credentials_file(), cfg.resolved_token_file())
        emails = client.fetch_messages(cfg.senders, cfg.lookback_days, max_results=max_results)

    # 1) Parse job postings from every email (all tabs already included).
    raw_jobs = []
    for email in emails:
        for job in parse_email(email):
            job.email_id = email.id
            raw_jobs.append(job)

    # 2) Filter -> enrich (early-apply + score) -> dedupe.
    jobs = process_jobs(raw_jobs, cfg)

    # 3) Detect application statuses.
    statuses = detect_statuses(emails, profile=cfg.name)

    # 4) Persist.
    jobs_new = 0
    statuses_new = 0
    with Storage(cfg.resolved_db_file()) as store:
        for j in jobs:
            if store.upsert_job(j):
                jobs_new += 1
        for s in statuses:
            if store.upsert_status(s):
                statuses_new += 1

    return SyncResult(
        profile=cfg.name,
        emails_read=len(emails),
        jobs_found=len(jobs),
        jobs_new=jobs_new,
        statuses_found=len(statuses),
        statuses_new=statuses_new,
    )
