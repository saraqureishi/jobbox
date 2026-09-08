"""Tests for CV match scoring, filtering, and the early-apply flag."""

import datetime as dt

from jobbox.config import ProfileConfig
from jobbox.models import Job
from jobbox.scoring import compute_match_score, matches_filters, is_early_apply


def _cfg(**kw):
    base = dict(name="t", cv_keywords=["python", "sql", "snowflake"],
                keywords=[], exclusions=[], early_apply_hours=24)
    base.update(kw)
    return ProfileConfig(**base)


def test_match_score_title_weighted():
    job = Job(company="Acme", title="Snowflake Python Engineer", location="London")
    score, matched = compute_match_score(job, ["python", "sql", "snowflake"])
    assert score > 0
    assert "python" in matched and "snowflake" in matched


def test_match_score_zero_when_no_overlap():
    job = Job(company="Acme", title="Barista", location="London")
    score, matched = compute_match_score(job, ["python", "sql"])
    assert score == 0
    assert matched == []


def test_filters_keyword_keeplist():
    cfg = _cfg(keywords=["part time"])
    keep = Job(company="X", title="Part time cashier", location="")
    drop = Job(company="Y", title="Full time manager", location="")
    assert matches_filters(keep, cfg) is True
    assert matches_filters(drop, cfg) is False


def test_filters_exclusions():
    cfg = _cfg(exclusions=["unpaid"])
    drop = Job(company="X", title="Unpaid intern", location="")
    assert matches_filters(drop, cfg) is False


def test_early_apply_flag():
    cfg = _cfg(early_apply_hours=24)
    recent = Job(company="X", title="Dev", location="",
                 posted_at=dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(hours=2))
    old = Job(company="Y", title="Dev", location="",
              posted_at=dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(hours=48))
    assert is_early_apply(recent, cfg) is True
    assert is_early_apply(old, cfg) is False
