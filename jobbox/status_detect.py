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
# STRONG applied signals: an unambiguous "we got your application" confirmation
# from an employer/ATS. These are trusted even if the email also contains
# generic newsletter words, because a real confirmation is unmistakable.
_APPLIED_STRONG_PATTERNS = [
    r"thank(?:s| you)? for (?:your )?appl(?:ying|ication)",
    r"thank you for applying to",
    r"thanks for your (?:job )?application",
    r"thank you for your submission",
    r"thank you for your interest in the .{0,40}\brole\b",
    r"we(?:'ve| have)? received your application",
    r"application (?:received|submitted|confirmed|complete)",
    r"your application (?:to|for|has been received|is complete)",
    r"successfully applied",
    r"we(?:'ve| have) got your application",
    r"we(?:'ll| will) review your application",
    r"application is (?:now )?(?:in|being reviewed)",
    # Job-board confirmations
    r"indeed application[:\s]",
    r"application (?:was )?(?:sent|submitted) to",
    r"you applied to",
    r"you(?:'ve| have) applied",
]

# WEAKER applied signals — only trusted when NOT in a newsletter/browse email.
_APPLIED_WEAK_PATTERNS = [
    r"we(?:'ll| will) help you get started",
    r"thrilled (?:that )?you(?:'re| are) interested",
    r"interested in joining (?:our|the) team",
]


# Newsletter / marketing / digest signals. If an email looks like a broadcast
# (not a personal update about YOUR application), we do NOT classify it — this
# stops "Application season is approaching!" style emails becoming fake
# "Interview" statuses.
_NEWSLETTER_PATTERNS = [
    r"\bnew roles?\b",
    r"\d+\s+new (?:jobs?|roles?|opportunit)",
    r"opportunities from employers",
    r"latest opportunities",
    r"jobs? (?:for you|picked for you|that match)",
    r"your (?:latest )?(?:job )?(?:update|alert)",
    r"application season",
    r"schemes unpacked",
    r"webinar",
    r"upcoming events",
    r"job alert",
    r"new match(?:es)?[:\s]",   # Otta/WTTJ "New match: ..." browse emails
    r"don'?t fall behind",
    r"are you ready",
    r"newsletter",
    r"this week'?s",
    r"top (?:picks|jobs)",
    r"reactivate your premium",
    r"you shared some .* account data",
]

# Personal-application signals: strongly indicate a real update about the
# user's own application. Presence of one of these lets a status through even
# if a newsletter word is also present.
_PERSONAL_PATTERNS = [
    r"your application",
    r"you applied",
    r"you(?:'ve| have) applied",
    r"thank you for (?:your )?appl",
    r"we received your application",
    r"regarding your application",
    r"update on your application",
    r"your interview",
    r"interview (?:invitation|invite) ",
    r"schedule your interview",
]


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_REJECTED_RE = _compile(_REJECTED_PATTERNS)
_INTERVIEW_RE = _compile(_INTERVIEW_PATTERNS)
_APPLIED_STRONG_RE = _compile(_APPLIED_STRONG_PATTERNS)
_APPLIED_WEAK_RE = _compile(_APPLIED_WEAK_PATTERNS)
_NEWSLETTER_RE = _compile(_NEWSLETTER_PATTERNS)
_PERSONAL_RE = _compile(_PERSONAL_PATTERNS)


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


def detect_status(email: EmailMessage, profile: str = "") -> Optional[ApplicationStatus]:
    """Classify a single email into an ApplicationStatus, or None.

    Priority (highest first):
      1. STRONG applied confirmation ("thank you for applying") -> Applied.
         Trusted even alongside newsletter words, because it's unmistakable.
      2. Rejection phrases -> Rejected.
      3. Personal interview invite -> Interview.
      4. Weak applied signal, only if NOT a newsletter/browse email -> Applied.
    Anything that is only a newsletter/browse/digest -> None.
    """
    text = _plaintext(email)
    is_newsletter = _any(_NEWSLETTER_RE, text)
    is_personal = _any(_PERSONAL_RE, text)

    # 1) Rejection first: "unfortunately / regret to inform / not successful"
    #    is specific and should win even when the email also thanks you for
    #    applying (rejections often open politely). Skip if clearly a newsletter.
    if _any(_REJECTED_RE, text) and not is_newsletter:
        return _make(email, STATUS_REJECTED, profile)

    # 2) Strong "we got your application" confirmation.
    if _any(_APPLIED_STRONG_RE, text):
        return _make(email, STATUS_APPLIED, profile)

    # 3) Interview — only when clearly personal AND not a browse/"new match".
    if _any(_INTERVIEW_RE, text) and is_personal and not is_newsletter:
        return _make(email, STATUS_INTERVIEW, profile)

    # 4) Weak applied signal, only outside newsletters.
    if _any(_APPLIED_WEAK_RE, text) and not is_newsletter:
        return _make(email, STATUS_APPLIED, profile)

    return None


def _from_ats(email: EmailMessage) -> bool:
    domain = email.sender_email.split("@")[-1] if "@" in email.sender_email else ""
    return any(domain.endswith(ats) for ats in ATS_DOMAINS)


def _company_from_subject(email: EmailMessage) -> str:
    """Pull a company from subjects like 'Thank you for applying to <Company>'."""
    subj = email.subject or ""
    m = re.search(r"appl(?:ying|ication)\s+to\s+([A-Z][\w&.\- ]{1,40})", subj)
    if m:
        # Trim a trailing " - <role>" so "Eaton - Data Analyst Intern" -> "Eaton".
        return m.group(1).split(" - ")[0].split(" \u2013 ")[0].strip(" -|.")
    m = re.search(r"from\s+([A-Z][\w&.\- ]{1,40})\s+[-–]", subj)  # "From Abound - thanks..."
    if m:
        return m.group(1).strip(" -|.")
    m = re.search(r"\|\s*([A-Z][\w&.\- ]{1,40})\s*$", subj)       # "... | Lendable"
    if m:
        return m.group(1).strip(" -|.")
    return ""


def _make(email: EmailMessage, status: str, profile: str) -> ApplicationStatus:
    company = _company_from_subject(email) or _guess_company(email) or "Unknown"
    return ApplicationStatus(
        company=company,
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
