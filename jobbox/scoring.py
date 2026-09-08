"""Enrichment: de-duplication, early-apply flag, and CV match scoring."""

from __future__ import annotations

import datetime as dt
import re
from typing import List

from .config import ProfileConfig
from .models import Job


def _now_utc() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def matches_filters(job: Job, cfg: ProfileConfig) -> bool:
    """Apply keyword keep-list and exclusion list to a job."""
    haystack = f"{job.title} {job.company} {job.location}".lower()

    for bad in cfg.exclusions:
        if bad.lower() in haystack:
            return False

    if cfg.keywords:
        return any(kw.lower() in haystack for kw in cfg.keywords)
    return True


def compute_match_score(job: Job, cv_keywords: List[str]) -> (int, List[str]):
    """Score 0-100 by fraction of CV keywords present in title/company.

    Title matches are weighted more heavily than company/location matches.
    """
    if not cv_keywords:
        return 0, []
    title = job.title.lower()
    rest = f"{job.company} {job.location}".lower()

    matched = []
    weight = 0.0
    for kw in cv_keywords:
        k = kw.lower()
        if k in title:
            matched.append(kw)
            weight += 1.0
        elif k in rest:
            matched.append(kw)
            weight += 0.4

    # Normalise: full weight if ~half the CV keywords hit the title.
    denom = max(1.0, len(cv_keywords) * 0.5)
    score = int(round(min(100.0, (weight / denom) * 100.0)))
    return score, matched


def is_early_apply(job: Job, cfg: ProfileConfig) -> bool:
    """True if the job was posted within cfg.early_apply_hours."""
    posted = job.posted_at or job.received_at
    if not posted:
        return False
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=dt.timezone.utc)
    age = _now_utc() - posted
    return age <= dt.timedelta(hours=cfg.early_apply_hours)


def enrich(job: Job, cfg: ProfileConfig) -> Job:
    """Fill in profile, early-apply flag and match score on a job in place."""
    job.profile = cfg.name
    job.early_apply = is_early_apply(job, cfg)
    score, matched = compute_match_score(job, cfg.cv_keywords)
    job.match_score = score
    job.matched_keywords = ", ".join(matched)
    return job


def dedupe(jobs: List[Job]) -> List[Job]:
    """De-duplicate a list of jobs, keeping the highest-scoring / earliest copy."""
    best = {}
    for j in jobs:
        k = j.dedup_key()
        if k not in best:
            best[k] = j
            continue
        # Prefer the one with a real posted time / higher score.
        cur = best[k]
        if (j.match_score, bool(j.posted_at)) > (cur.match_score, bool(cur.posted_at)):
            best[k] = j
    return list(best.values())


def process_jobs(jobs: List[Job], cfg: ProfileConfig) -> List[Job]:
    """Full pipeline: filter -> enrich -> dedupe."""
    kept = [j for j in jobs if matches_filters(j, cfg)]
    for j in kept:
        enrich(j, cfg)
    return dedupe(kept)
