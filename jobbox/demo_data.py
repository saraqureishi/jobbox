"""Synthetic email fixtures so JobBox can be run/demoed without a Gmail account.

Used by ``jobbox demo --profile X``. The emails mimic real alert HTML closely
enough to exercise the parsers, plus a few application-update emails to
exercise status detection.
"""

from __future__ import annotations

import datetime as dt
from typing import List

from .gmail_client import EmailMessage


def _dt(hours_ago: float) -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(hours=hours_ago)


def _msg(**kw) -> EmailMessage:
    kw.setdefault("thread_id", kw["id"])
    kw.setdefault("snippet", "")
    kw.setdefault("text_body", "")
    kw.setdefault("html_body", "")
    kw.setdefault("labels", [])
    return EmailMessage(**kw)


def demo_emails() -> List[EmailMessage]:
    emails: List[EmailMessage] = []

    # --- LinkedIn job alert (in "Updates" tab in real Gmail) ---
    emails.append(_msg(
        id="li-1",
        sender="LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        sender_email="jobalerts-noreply@linkedin.com",
        subject="4 new jobs for 'data engineer'",
        date=_dt(2),
        html_body="""
        <table>
          <tr><td>
            <a href="https://www.linkedin.com/comm/jobs/view/123?trk=eml">Data Engineer</a>
            <div>Monzo · London · 3 hours ago</div>
          </td></tr>
          <tr><td>
            <a href="https://www.linkedin.com/comm/jobs/view/124?trk=eml">Junior Python Developer</a>
            <div>Revolut · Remote · 1 day ago</div>
          </td></tr>
          <tr><td>
            <a href="https://www.linkedin.com/comm/jobs/view/125?trk=eml">Snowflake Data Analyst</a>
            <div>Deliveroo · London · 5 hours ago</div>
          </td></tr>
        </table>""",
    ))

    # --- Indeed alert (duplicate of the Monzo role, different URL) ---
    emails.append(_msg(
        id="in-1",
        sender="Indeed <noreply@indeed.com>",
        sender_email="noreply@indeed.com",
        subject="New data engineer jobs",
        date=_dt(6),
        html_body="""
        <div>
          <a href="https://uk.indeed.com/rc/clk?jk=aaa">Data Engineer</a>
          <div>Monzo · London</div>
          <a href="https://uk.indeed.com/rc/clk?jk=bbb">Weekend Sales Assistant</a>
          <div>Tesco · Manchester · 12 hours ago</div>
        </div>""",
    ))

    # --- Otta alert ---
    emails.append(_msg(
        id="ot-1",
        sender="Otta <noreply@otta.com>",
        sender_email="noreply@otta.com",
        subject="Jobs picked for you",
        date=_dt(20),
        html_body="""
        <div>
          <a href="https://app.otta.com/jobs/xyz">Machine Learning Engineer</a>
          <div>Cohere · Remote (within the UK) · 2 hours ago</div>
        </div>""",
    ))

    # --- Application updates (status detection) ---
    emails.append(_msg(
        id="app-1",
        sender="Monzo Careers <no-reply@monzo.greenhouse.io>",
        sender_email="no-reply@monzo.greenhouse.io",
        subject="Thank you for applying to Monzo",
        date=_dt(30),
        text_body="Hi Sara, thank you for your application to the Data Engineer role. "
                  "We have received your application and will be in touch.",
    ))
    emails.append(_msg(
        id="app-2",
        sender="Morrisons Talent <careers@morrisons.lever.co>",
        sender_email="careers@morrisons.lever.co",
        subject="Interview invitation — Data Analyst",
        date=_dt(10),
        text_body="Hi Sara, we'd love to schedule a call to chat about the role. "
                  "Please share your availability for a phone screen next week.",
    ))
    emails.append(_msg(
        id="app-3",
        sender="Deliveroo Recruiting <noreply@deliveroo.workable.com>",
        sender_email="noreply@deliveroo.workable.com",
        subject="Update on your application",
        date=_dt(48),
        text_body="Thank you for your interest. Unfortunately we have decided not to "
                  "move forward with your application at this time. We wish you the best.",
    ))
    emails.append(_msg(
        id="app-4",
        sender="Revolut <no-reply@revolut.ashbyhq.com>",
        sender_email="no-reply@revolut.ashbyhq.com",
        subject="We received your application",
        date=_dt(72),
        text_body="Thanks for applying to Revolut! Your application has been received.",
    ))

    return emails
