"""Auto-detect application statuses (Applied / Interview / Rejected) from email.

These are the "Application updates" JobBox surfaces: emails from a company (or
an ATS like Greenhouse/Lever/Workday) that indicate progress on an application.

Detection is keyword/phrase based and deliberately conservative. Every result
is marked ``confidence="auto"`` so the dashboard can ask "Did we read this
right?" — exactly like the real JobBox does.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .gmail_client import EmailMessage
from .models import (
    STATUS_APPLIED,
    STATUS_INTERVIEW,
    STATUS_REJECTED,
    ApplicationStatus,
)

# Applicant Tracking Systems — strong signal an email is application-related.
ATS_DOMAINS = (
    "greenhouse.io", "lever.co", "myworkday.com", "workday.com", "smartrecruiters.com",
    "icims.com", "ashbyhq.com", "successfactors.com", "taleo.net", "bamboohr.com",
    "workable.com", "teamtailor.com", "jobvite.com",
)

# Ordered by priority: check Rejected first (most specific), then Interview,
# then Applied (most generic), so a rejection isn't mislabelled as "applied".
_REJECTED_PATTERNS = [
    r"\bunfortunately\b",
    r"we (?:have )?decided (?:not|to move forward with other)",
    r"not (?:been )?(?:successful|selected|moving forward|progressing)",
    r"will not be (?:progressing|proceeding|moving forward)",
    r"regret to inform",
    r"other candidates",
    r"position has been filled",
    r"pursue other (?:candidates|applicants)",
    r"no longer under consideration",
]
_INTERVIEW_PATTERNS = [
    r"\binterview\b",
    r"schedule (?:a|your) (?:call|chat|screen|conversation)",
    r"phone screen",
    r"technical (?:screen|assessment|test)",
    r"(?:availability|available) (?:for|to) (?:a )?(?:call|chat|meeting)",
    r"next (?:round|stage|step)",
    r"meet (?:the|our) team",
    r"assessment (?:centre|center)",
    r"take[- ]home",
]
_APPLIED_PATTERNS = [
    r"thank you for (?:your )?appl(?:ying|ication)",
    r"we(?:'ve| have)? received your application",
    r"application (?:received|submitted|confirmed|complete)",
    r"your application (?:to|for|has been received)",
    r"successfully applied",
    r"thanks for applying",
    # Indeed / job-board confirmations
    r"indeed application[:\s]",
    r"application (?:was )?(?:sent|submitted) to",
    r"you applied to",
    r"you(?:'ve| have) applied",
    r"we(?:'ll| will) help you get started",
    # Employer acknowledgement phrasing (e.g. David Lloyd)
    r"thrilled (?:that )?you(?:'re| are) interested",
    r"interested in joining (?:our|the) team",
    r"we(?:'ve| have) got your application",
    r"application is (?:now )?(?:in|being reviewed)",
]


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_REJECTED_RE = _compile(_REJECTED_PATTERNS)
_INTERVIEW_RE = _compile(_INTERVIEW_PATTERNS)
_APPLIED_RE = _compile(_APPLIED_PATTERNS)


def _any(res, text: str) -> bool:
    return any(r.search(text) for r in res)


def _plaintext(email: EmailMessage) -> str:
    """Return a text blob (subject + body) suitable for phrase matching."""
    body = email.text_body
    if not body and email.html_body:
        # Cheap tag strip; good enough for phrase detection.
        body = re.sub(r"<[^>]+>", " ", email.html_body)
    return f"{email.subject}\n{body}"


def _guess_company(email: EmailMessage) -> str:
    """Guess the company from the sender display name or domain."""
    if "<" in email.sender:
        name = email.sender.split("<", 1)[0].strip().strip('"')
        if name and "no-reply" not in name.lower() and "noreply" not in name.lower():
            return name
    domain = email.sender_email.split("@")[-1] if "@" in email.sender_email else ""
    # Strip ATS host, keep the sub-label if present (e.g. acme.greenhouse.io).
    for ats in ATS_DOMAINS:
        if domain.endswith(ats):
            sub = domain[: -len(ats)].strip(".")
            if sub:
                return sub.split(".")[-1].capitalize()
    base = domain.split(".")[0] if domain else ""
    return base.capitalize()


def looks_like_application_email(email: EmailMessage) -> bool:
    """Heuristic gate before we try to classify status."""
    domain = email.sender_email.split("@")[-1] if "@" in email.sender_email else ""
    if any(domain.endswith(ats) for ats in ATS_DOMAINS):
        return True
    # Job-board "you applied" senders (e.g. Indeed Apply).
    sender_blob = f"{email.sender} {email.sender_email}".lower()
    if "indeed" in sender_blob and "appl" in f"{email.subject}".lower():
        return True
    text = _plaintext(email).lower()
    return _any(_REJECTED_RE, text) or _any(_INTERVIEW_RE, text) or _any(_APPLIED_RE, text)


def detect_status(email: EmailMessage, profile: str = "") -> Optional[ApplicationStatus]:
    """Classify a single email into an ApplicationStatus, or None."""
    if not looks_like_application_email(email):
        return None

    text = _plaintext(email)

    status = None
    if _any(_REJECTED_RE, text):
        status = STATUS_REJECTED
    elif _any(_INTERVIEW_RE, text):
        status = STATUS_INTERVIEW
    elif _any(_APPLIED_RE, text):
        status = STATUS_APPLIED

    if status is None:
        return None

    return ApplicationStatus(
        company=_guess_company(email) or "Unknown",
        status=status,
        profile=profile,
        email_id=email.id,
        detected_at=email.date,
        subject=email.subject,
        confidence="auto",
    )


def detect_statuses(emails: List[EmailMessage], profile: str = "") -> List[ApplicationStatus]:
    out = []
    for e in emails:
        s = detect_status(e, profile)
        if s:
            out.append(s)
    return out
