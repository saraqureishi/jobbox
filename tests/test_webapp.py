"""Tests for the web layer helpers (cross-platform date formatting)."""

import datetime as dt

from jobbox.webapp import _date_label, _group_jobs_by_date


def test_date_label_today_yesterday():
    now = dt.datetime.now(tz=dt.timezone.utc)
    assert _date_label(now) == "Today"
    assert _date_label(now - dt.timedelta(days=1)) == "Yesterday"


def test_date_label_older_is_cross_platform():
    """Must not use %-d / %#d (which raise ValueError on Windows)."""
    old = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=9)
    label = _date_label(old)  # should not raise on any OS
    assert "," in label
    # Day number rendered without leading zero, no format codes leaked.
    assert "%" not in label


def test_group_jobs_by_date_handles_missing_and_old_dates():
    now = dt.datetime.now(tz=dt.timezone.utc)
    jobs = [
        {"received_at": now.isoformat(), "title": "A"},
        {"received_at": (now - dt.timedelta(days=5)).isoformat(), "title": "B"},
        {"received_at": None, "posted_at": None, "title": "C"},  # -> "Earlier"
    ]
    groups = _group_jobs_by_date(jobs)
    assert "Today" in groups
    assert "Earlier" in groups
    # Every job is placed in exactly one group.
    assert sum(len(v) for v in groups.values()) == 3
