"""Core data models shared across parsing, storage, scoring and the web app."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional


def _norm(text: str) -> str:
    """Lower-case, collapse whitespace, strip punctuation for stable hashing."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class Job:
    """A single job posting extracted from an email."""

    company: str
    title: str
    location: str = ""
    url: str = ""
    source: str = ""              # e.g. "linkedin", "indeed", "generic"
    profile: str = ""             # which inbox profile it came from
    email_id: str = ""            # source Gmail message id
    posted_at: Optional[dt.datetime] = None   # when the job was posted (if known)
    received_at: Optional[dt.datetime] = None  # when the alert email arrived
    early_apply: bool = False     # posted within early_apply_hours
    match_score: int = 0          # 0-100 fit vs CV keywords
    matched_keywords: str = ""    # comma-joined keywords that matched

    def dedup_key(self) -> str:
        """Stable identity for de-duplication.

        We key on normalised company+title+location so the SAME role from two
        different sources (e.g. LinkedIn and Indeed, which use different URLs)
        collapses into one entry — the core JobBox promise. If company is
        unknown, fall back to the canonical URL to avoid over-merging.
        """
        if _norm(self.company):
            basis = f"{_norm(self.company)}|{_norm(self.title)}|{_norm(self.location)}"
            return hashlib.sha1(basis.encode("utf-8")).hexdigest()
        if self.url:
            canonical = self.url.split("?", 1)[0].rstrip("/").lower()
            return hashlib.sha1(canonical.encode("utf-8")).hexdigest()
        basis = f"{_norm(self.title)}|{_norm(self.location)}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()


# Recognised application-status values.
STATUS_APPLIED = "Applied"
STATUS_INTERVIEW = "Interview"
STATUS_REJECTED = "Rejected"
VALID_STATUSES = (STATUS_APPLIED, STATUS_INTERVIEW, STATUS_REJECTED)


@dataclass
class ApplicationStatus:
    """A detected application-status update for a company."""

    company: str
    status: str                    # one of VALID_STATUSES
    profile: str = ""
    email_id: str = ""
    detected_at: Optional[dt.datetime] = None
    subject: str = ""              # source subject, for the "did we read this right?" UI
    confidence: str = "auto"       # "auto" | "confirmed" | "rejected_by_user"

    def key(self) -> str:
        basis = f"{_norm(self.company)}|{self.status}|{self.email_id}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()
