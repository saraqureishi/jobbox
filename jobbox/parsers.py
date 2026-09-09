"""Turn job-alert emails into structured :class:`Job` records.

Strategy:
  * Sender-specific parsers for the common alert providers (LinkedIn, Indeed,
    Glassdoor, Otta / Welcome to the Jungle) that understand their HTML layout.
  * A generic HTML fallback that scrapes job-like links from any other alert.

Every parser returns a list of Jobs. The dispatcher :func:`parse_email` picks
the best parser by sender domain and falls back to generic.

Parsers are written against the plain :class:`EmailMessage` so they can be
unit-tested with HTML fixtures — no live Gmail needed.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from .gmail_client import EmailMessage
from .models import Job

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

_POSTED_RE = re.compile(
    r"(\d+)\s*(minute|min|hour|hr|day|week|month)s?\s*ago", re.IGNORECASE
)


def parse_relative_posted(text: str, reference: dt.datetime) -> Optional[dt.datetime]:
    """Parse '3 hours ago' / '2 days ago' relative to ``reference`` (email date)."""
    if not text:
        return None
    m = _POSTED_RE.search(text)
    if not m:
        # "just posted" / "today" / "new"
        low = text.lower()
        if any(w in low for w in ("just posted", "posted today", "new job", "just now")):
            return reference
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "minute": dt.timedelta(minutes=n),
        "min": dt.timedelta(minutes=n),
        "hour": dt.timedelta(hours=n),
        "hr": dt.timedelta(hours=n),
        "day": dt.timedelta(days=n),
        "week": dt.timedelta(weeks=n),
        "month": dt.timedelta(days=30 * n),
    }.get(unit)
    if delta is None:
        return None
    return reference - delta


def clean_url(url: str) -> str:
    """Unwrap common tracking redirects and drop query strings.

    LinkedIn/Indeed wrap the real URL; where we can, extract it.
    """
    if not url:
        return ""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    # Common patterns: ?url=<real>, ?u=<real>, ?targetUrl=<real>
    for key in ("url", "u", "targetUrl", "target"):
        if key in qs and qs[key]:
            inner = unquote(qs[key][0])
            if inner.startswith("http"):
                return inner.split("?", 1)[0]
    return url.split("?", 1)[0]


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def _local_context(a) -> str:
    """Company/location text local to a job link, WITHOUT bleeding into the
    next job in the same parent container.

    Alert emails usually put "Company · Location · posted" in the element(s)
    immediately after the title link. We collect the nearest following
    siblings (or, if none, the link's own parent minus deeper job links).
    """
    # 1) Prefer immediate following siblings until we hit another link.
    chunks = []
    sib = a.next_sibling
    steps = 0
    while sib is not None and steps < 4:
        steps += 1
        name = getattr(sib, "name", None)
        if name == "a":  # next job starts
            break
        text = _text(sib) if name else re.sub(r"\s+", " ", str(sib)).strip()
        if text:
            chunks.append(text)
        sib = sib.next_sibling
    if chunks:
        return " ".join(chunks)

    # 2) Fall back to the parent, but strip out any OTHER anchor text so a
    #    sibling job's title/company doesn't leak in.
    parent = a.find_parent(["td", "div", "li"]) or a.parent
    if parent is None:
        return ""
    import copy

    clone = copy.copy(parent)
    for other in clone.find_all("a"):
        other.extract()
    return _text(clone)


# Prefer the fast lxml parser if it's installed, but fall back to Python's
# built-in html.parser so JobBox works with zero compiler/build dependencies
# (lxml needs prebuilt wheels or a C compiler; html.parser is always available).
try:
    import lxml  # noqa: F401

    _BS_PARSER = "lxml"
except ImportError:  # pragma: no cover
    _BS_PARSER = "html.parser"


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", _BS_PARSER)


# ----------------------------------------------------------------------------
# Sender-specific parsers
# ----------------------------------------------------------------------------

def parse_linkedin(email: EmailMessage) -> List[Job]:
    """LinkedIn job alerts: each job is a block with a title link, company, location."""
    jobs: List[Job] = []
    soup = _soup(email.body)

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "linkedin.com/comm/jobs/view" not in href and "/jobs/view/" not in href:
            continue
        title = _text(a)
        if not title or len(title) < 3:
            continue
        # Company / location typically sit in sibling text near the link.
        ctx = _local_context(a)
        company, location = _guess_company_location(ctx, title)
        posted = parse_relative_posted(ctx, email.date)
        jobs.append(
            Job(
                company=company,
                title=title,
                location=location,
                url=clean_url(href),
                source="linkedin",
                posted_at=posted,
                received_at=email.date,
            )
        )
    return _dedupe_within_email(jobs)


def parse_indeed(email: EmailMessage) -> List[Job]:
    jobs: List[Job] = []
    soup = _soup(email.body)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "indeed.com" not in href or ("/rc/clk" not in href and "/pagead" not in href and "viewjob" not in href):
            continue
        title = _text(a)
        if not title or len(title) < 3:
            continue
        ctx = _local_context(a)
        company, location = _guess_company_location(ctx, title)
        jobs.append(
            Job(
                company=company,
                title=title,
                location=location,
                url=clean_url(href),
                source="indeed",
                posted_at=parse_relative_posted(ctx, email.date),
                received_at=email.date,
            )
        )
    return _dedupe_within_email(jobs)


def parse_glassdoor(email: EmailMessage) -> List[Job]:
    jobs: List[Job] = []
    soup = _soup(email.body)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "glassdoor.com" not in href or "job-listing" not in href and "partner/jobListing" not in href:
            continue
        title = _text(a)
        if not title or len(title) < 3:
            continue
        ctx = _local_context(a)
        company, location = _guess_company_location(ctx, title)
        jobs.append(
            Job(
                company=company,
                title=title,
                location=location,
                url=clean_url(href),
                source="glassdoor",
                posted_at=parse_relative_posted(ctx, email.date),
                received_at=email.date,
            )
        )
    return _dedupe_within_email(jobs)


def parse_otta(email: EmailMessage) -> List[Job]:
    """Otta / Welcome to the Jungle."""
    jobs: List[Job] = []
    soup = _soup(email.body)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not any(d in href for d in ("otta.com", "welcometothejungle.com")):
            continue
        title = _text(a)
        if not title or len(title) < 3 or title.lower() in ("view job", "apply", "see more"):
            continue
        ctx = _local_context(a)
        company, location = _guess_company_location(ctx, title)
        jobs.append(
            Job(
                company=company,
                title=title,
                location=location,
                url=clean_url(href),
                source="otta",
                posted_at=parse_relative_posted(ctx, email.date),
                received_at=email.date,
            )
        )
    return _dedupe_within_email(jobs)


# ----------------------------------------------------------------------------
# Generic fallback
# ----------------------------------------------------------------------------

_JOB_HINT_WORDS = (
    # tech / data
    "engineer", "developer", "analyst", "intern", "manager", "scientist",
    "designer", "consultant", "specialist", "associate", "graduate",
    "fellow", "lead", "architect",
    # admin / office / customer-facing (part-time / non-tech roles)
    "administrator", "admin", "assistant", "coordinator", "receptionist",
    "reception", "front of house", "customer service", "customer support",
    "customer experience", "advisor", "adviser", "clerk", "data entry",
    "call handler", "contact centre", "contact center", "concierge",
    "host", "hostess", "steward", "usher", "ambassador", "invigilator",
    "note-taker", "notetaker", "mentor", "tutor", "guest services",
    "guest experience", "guest relations", "visitor experience", "greeter",
    "meet and greet", "booking", "scheduling", "records", "secretary",
    "officer", "representative", "agent", "support", "services",
)
_NON_JOB_LINK = (
    "unsubscribe", "privacy", "manage", "settings", "help", "view in browser",
    "app store", "google play", "download", "terms", "contact us",
)


def parse_generic(email: EmailMessage) -> List[Job]:
    """Best-effort scrape for any alert we don't have a dedicated parser for."""
    jobs: List[Job] = []
    soup = _soup(email.body)

    for a in soup.find_all("a", href=True):
        title = _text(a)
        low = title.lower()
        if not title or len(title) < 5:
            continue
        if any(w in low for w in _NON_JOB_LINK):
            continue
        # Treat as a job if the link text looks like a role.
        if not any(w in low for w in _JOB_HINT_WORDS):
            continue
        ctx = _local_context(a)
        company, location = _guess_company_location(ctx, title)
        jobs.append(
            Job(
                company=company or _sender_name(email),
                title=title,
                location=location,
                url=clean_url(a["href"]),
                source="generic",
                posted_at=parse_relative_posted(ctx, email.date),
                received_at=email.date,
            )
        )

    # Fallback: some alert providers (Reed, NHS Jobs, some Indeed digests) put
    # the role in the SUBJECT line rather than as clean job links, e.g.
    # "Added today: new customer service in HA27QN". If we found nothing from
    # links but the subject looks like a role, capture it from the subject so
    # keyword filtering and exclusions still work.
    if not jobs:
        job_from_subject = _job_from_subject(email)
        if job_from_subject is not None:
            jobs.append(job_from_subject)

    return _dedupe_within_email(jobs)


# Words/prefixes to strip from alert subjects to isolate the role text.
_SUBJECT_NOISE = re.compile(
    r"^(added today[:\-]?|new|newest|latest|today'?s?|job alert[:\-]?|"
    r"jobs? for you[:\-]?|we found|here are|\d+\s+new)\s*",
    re.IGNORECASE,
)


def _job_from_subject(email: EmailMessage):
    """Extract a best-effort Job from the email subject line, or None."""
    subject = (email.subject or "").strip()
    low = subject.lower()
    if not subject or not any(w in low for w in _JOB_HINT_WORDS):
        return None

    # Clean common alert prefixes and quoting. Apply repeatedly since alerts
    # often stack prefixes, e.g. "Added today: new <role>".
    cleaned = subject
    for _ in range(3):
        new = _SUBJECT_NOISE.sub("", cleaned).strip(" '\"“”‘’")
        if new == cleaned:
            break
        cleaned = new
    # Drop trailing "jobs & vacancies" style noise.
    cleaned = re.sub(r"\b(jobs?|vacanc(y|ies))\b.*$", "", cleaned, flags=re.IGNORECASE).strip(" -·|")

    # Pull out a location if the subject has "... in <place>".
    location = ""
    m = re.search(r"\bin\s+([A-Za-z0-9 ,]+)$", cleaned)
    if m:
        location = m.group(1).strip()
        cleaned = cleaned[: m.start()].strip(" -·|")

    title = cleaned or subject
    return Job(
        company=_sender_name(email),
        title=title,
        location=location,
        url="",
        source="subject",
        posted_at=email.date,
        received_at=email.date,
    )


# ----------------------------------------------------------------------------
# Shared extraction heuristics
# ----------------------------------------------------------------------------

# Locations we commonly see; extend freely. Used to split "company · location".
_LOCATION_HINTS = re.compile(
    r"\b(remote|hybrid|london|manchester|birmingham|leeds|bristol|edinburgh|"
    r"glasgow|dublin|new york|san francisco|berlin|paris|amsterdam|uk|"
    r"united kingdom|england|scotland|wales|"
    # Greater London areas / boroughs commonly seen in Reed/Indeed alerts
    r"harrow|heathrow|wembley|croydon|ealing|barnet|brent|camden|westminster|"
    r"hounslow|richmond|kingston|watford|uxbridge|greenford|middlesex|"
    # UK postcode outward codes (e.g. HA2, EC1, SW1) — matches "HA27QN" too
    r"[a-z]{1,2}\d[a-z\d]?(?:\s?\d[a-z]{2})?)\b",
    re.IGNORECASE,
)


def _guess_company_location(context: str, title: str):
    """Given the text block around a job link, guess (company, location)."""
    ctx = context.replace(title, " ").strip(" ·-|,")
    # Split on common separators used in alert emails.
    pieces = re.split(r"\s*[·|–—]\s*|\s{2,}", ctx)
    pieces = [p.strip(" -,") for p in pieces if p and p.strip(" -,")]

    company = ""
    location = ""
    for p in pieces:
        if not location and _LOCATION_HINTS.search(p):
            location = p
        elif not company and 1 < len(p) < 60 and not _LOCATION_HINTS.search(p):
            company = p
    # If we still have no location but the context mentions one, grab it.
    if not location:
        m = _LOCATION_HINTS.search(ctx)
        if m:
            location = m.group(0)
    return company, location


def _sender_name(email: EmailMessage) -> str:
    if "<" in email.sender:
        return email.sender.split("<", 1)[0].strip().strip('"')
    return email.sender_email.split("@", 1)[0]


def _dedupe_within_email(jobs: List[Job]) -> List[Job]:
    seen = set()
    out = []
    for j in jobs:
        k = j.dedup_key()
        if k in seen:
            continue
        seen.add(k)
        out.append(j)
    return out


# ----------------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------------

_DOMAIN_PARSERS: Dict[str, Callable[[EmailMessage], List[Job]]] = {
    "linkedin.com": parse_linkedin,
    "indeed.com": parse_indeed,
    "glassdoor.com": parse_glassdoor,
    "otta.com": parse_otta,
    "welcometothejungle.com": parse_otta,
}


def parse_email(email: EmailMessage) -> List[Job]:
    """Dispatch to the right parser by sender domain, else generic fallback."""
    domain = email.sender_email.split("@")[-1] if "@" in email.sender_email else ""
    for known_domain, parser in _DOMAIN_PARSERS.items():
        if domain.endswith(known_domain):
            jobs = parser(email)
            if jobs:
                return jobs
            break  # known sender but nothing found -> try generic below
    return parse_generic(email)
