"""Tests for application-status auto-detection."""

import datetime as dt

from jobbox.gmail_client import EmailMessage
from jobbox.models import STATUS_APPLIED, STATUS_INTERVIEW, STATUS_REJECTED
from jobbox.status_detect import detect_status


def _email(subject, body, sender_email="careers@acme.com", sender="Acme <careers@acme.com>"):
    return EmailMessage(
        id="e", thread_id="t", sender=sender, sender_email=sender_email,
        subject=subject, date=dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc),
        text_body=body,
    )


def test_detect_applied():
    s = detect_status(_email("Thanks", "Thank you for your application to Acme."))
    assert s is not None and s.status == STATUS_APPLIED


def test_detect_interview():
    # A real interview email references the user's own application.
    s = detect_status(_email(
        "Your application - next steps",
        "Regarding your application, we'd love to schedule a call for a phone screen.",
    ))
    assert s is not None and s.status == STATUS_INTERVIEW


def test_newsletter_not_tagged_as_interview():
    """Marketing/newsletter emails mentioning interviews must be skipped."""
    s = detect_status(_email(
        "Application season is fast approaching. Are you ready?",
        "Don't fall behind! Here are tips to prepare for your interviews this season.",
        sender_email="ella@brightnetwork.co.uk",
        sender="Ella @ Bright Network <ella@brightnetwork.co.uk>",
    ))
    assert s is None


def test_new_roles_digest_not_tagged():
    s = detect_status(_email(
        "97 new roles",
        "View this email in your browser. 97 new roles from employers you follow.",
        sender_email="jobs@80000hours.org",
        sender="80,000 Hours <jobs@80000hours.org>",
    ))
    assert s is None


def test_detect_rejected():
    s = detect_status(_email("Update", "Unfortunately we have decided not to move forward."))
    assert s is not None and s.status == STATUS_REJECTED


def test_rejected_beats_applied_when_both_present():
    body = "Thank you for your application. Unfortunately we will not be progressing."
    s = detect_status(_email("Update", body))
    assert s.status == STATUS_REJECTED


def test_non_application_email_ignored():
    s = detect_status(_email("Newsletter", "Check out our latest blog posts and deals."))
    assert s is None


def test_ats_domain_recognised():
    s = detect_status(_email(
        "Application", "We received your application.",
        sender_email="no-reply@acme.greenhouse.io",
        sender="Acme <no-reply@acme.greenhouse.io>",
    ))
    assert s is not None and s.status == STATUS_APPLIED
