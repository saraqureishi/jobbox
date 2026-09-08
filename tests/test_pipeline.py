"""End-to-end pipeline test using demo data and a temp database."""

from jobbox.config import ProfileConfig
from jobbox.demo_data import demo_emails
from jobbox.pipeline import sync_profile
from jobbox.storage import Storage


def _cfg(tmp_path):
    cfg = ProfileConfig(
        name="t",
        cv_keywords=["python", "sql", "snowflake", "data", "machine learning"],
    )
    # Redirect the DB into pytest's tmp dir.
    cfg.resolved_db_file = lambda: tmp_path / "jobbox_t.db"  # type: ignore
    return cfg


def test_full_sync_with_demo_data(tmp_path):
    cfg = _cfg(tmp_path)
    result = sync_profile(cfg, emails=demo_emails())

    assert result.jobs_new > 0
    assert result.statuses_new > 0

    with Storage(cfg.resolved_db_file()) as s:
        jobs = s.get_jobs()
        # The Monzo Data Engineer arrives via LinkedIn AND Indeed -> deduped.
        monzo = [j for j in jobs if j["company"] == "Monzo" and j["title"] == "Data Engineer"]
        assert len(monzo) == 1

        # Snowflake Data Analyst should score highly against the CV keywords.
        snow = next(j for j in jobs if "Snowflake" in j["title"])
        assert snow["match_score"] >= 50

        counts = s.status_counts()
        assert counts.get("Applied", 0) >= 1
        assert counts.get("Interview", 0) >= 1
        assert counts.get("Rejected", 0) >= 1


def test_sync_is_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    first = sync_profile(cfg, emails=demo_emails())
    second = sync_profile(cfg, emails=demo_emails())
    # Re-running must not create duplicate rows.
    assert second.jobs_new == 0
    assert second.statuses_new == 0
    assert first.jobs_found == second.jobs_found
