"""Tests for email parsing and de-duplication (no Gmail needed)."""

import datetime as dt

from jobbox.gmail_client import EmailMessage
from jobbox.parsers import parse_email, clean_url, parse_relative_posted
from jobbox.scoring import dedupe


def _email(**kw):
    kw.setdefault("thread_id", kw.get("id", "t"))
    kw.setdefault("snippet", "")
    kw.setdefault("text_body", "")
    kw.setdefault("html_body", "")
    kw.setdefault("labels", [])
    kw.setdefault("date", dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc))
    return EmailMessage(**kw)


def test_linkedin_parse_multiple_jobs():
    email = _email(
        id="li",
        sender="LinkedIn <jobalerts-noreply@linkedin.com>",
        sender_email="jobalerts-noreply@linkedin.com",
        subject="jobs",
        html_body="""
        <table>
          <tr><td><a href="https://www.linkedin.com/comm/jobs/view/1">Data Engineer</a>
              <div>Monzo · London · 3 hours ago</div></td></tr>
          <tr><td><a href="https://www.linkedin.com/comm/jobs/view/2">ML Engineer</a>
              <div>Cohere · Remote · 1 day ago</div></td></tr>
        </table>""",
    )
    jobs = parse_email(email)
    titles = {j.title for j in jobs}
    assert titles == {"Data Engineer", "ML Engineer"}
    monzo = next(j for j in jobs if j.title == "Data Engineer")
    assert monzo.company == "Monzo"
    assert monzo.location == "London"
    assert monzo.source == "linkedin"


def test_context_does_not_bleed_between_jobs():
    """Company/location of one job must not leak into the next."""
    email = _email(
        id="in",
        sender="Indeed <noreply@indeed.com>",
        sender_email="noreply@indeed.com",
        subject="jobs",
        html_body="""
        <div>
          <a href="https://uk.indeed.com/rc/clk?jk=a">Data Engineer</a>
          <div>Monzo · London</div>
          <a href="https://uk.indeed.com/rc/clk?jk=b">Sales Assistant</a>
          <div>Tesco · Manchester</div>
        </div>""",
    )
    jobs = parse_email(email)
    sales = next(j for j in jobs if j.title == "Sales Assistant")
    assert sales.company == "Tesco"
    assert "Monzo" not in sales.location
    assert "Data Engineer" not in sales.location


def test_dedupe_merges_same_role_across_sources():
    """Same company+title+location from LinkedIn and Indeed -> one job."""
    from jobbox.models import Job

    j1 = Job(company="Monzo", title="Data Engineer", location="London",
             url="https://linkedin.com/x", source="linkedin")
    j2 = Job(company="Monzo", title="Data Engineer", location="London",
             url="https://indeed.com/y", source="indeed")
    merged = dedupe([j1, j2])
    assert len(merged) == 1


def test_clean_url_unwraps_redirect():
    wrapped = "https://t.example.com/click?url=https%3A%2F%2Fjobs.co%2F123&x=1"
    assert clean_url(wrapped) == "https://jobs.co/123"


def test_parse_relative_posted_hours():
    ref = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)
    got = parse_relative_posted("Posted 3 hours ago", ref)
    assert got == ref - dt.timedelta(hours=3)
