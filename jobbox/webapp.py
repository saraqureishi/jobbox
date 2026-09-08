"""Flask web dashboard — JobBox-style Jobs / Saved / Insights views."""

from __future__ import annotations

import datetime as dt
from collections import OrderedDict
from typing import Dict, List

from flask import Flask, jsonify, redirect, render_template, request, url_for

from .config import ProfileConfig
from .storage import Storage


def _parse_iso(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _date_label(d: dt.datetime) -> str:
    """'Today' / 'Yesterday' / 'Sunday, Sep 6' style grouping like JobBox."""
    today = dt.datetime.now(tz=dt.timezone.utc).date()
    day = d.date()
    if day == today:
        return "Today"
    if day == today - dt.timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %b %-d") if hasattr(d, "strftime") else str(day)


def _group_jobs_by_date(jobs: List[dict]) -> "OrderedDict[str, list]":
    groups: "OrderedDict[str, list]" = OrderedDict()
    for j in jobs:
        d = _parse_iso(j.get("received_at")) or _parse_iso(j.get("posted_at"))
        label = _date_label(d) if d else "Earlier"
        groups.setdefault(label, []).append(j)
    return groups


def create_app(cfg: ProfileConfig) -> Flask:
    app = Flask(__name__)
    app.config["CFG"] = cfg

    def store() -> Storage:
        return Storage(cfg.resolved_db_file())

    @app.route("/")
    def jobs_view():
        with store() as s:
            jobs = s.get_jobs(order=request.args.get("order", "received"))
            statuses = s.get_statuses()
            summary = s.summary()
        groups = _group_jobs_by_date(jobs)
        return render_template(
            "jobs.html",
            title=cfg.dashboard_title,
            active="jobs",
            groups=groups,
            statuses=statuses,
            summary=summary,
            profile=cfg.name,
        )

    @app.route("/saved")
    def saved_view():
        with store() as s:
            jobs = s.get_jobs(saved_only=True, order="score")
            summary = s.summary()
        return render_template(
            "saved.html",
            title=cfg.dashboard_title,
            active="saved",
            jobs=jobs,
            summary=summary,
            profile=cfg.name,
        )

    @app.route("/insights")
    def insights_view():
        with store() as s:
            per_week = s.applications_per_week()
            counts = s.status_counts()
            rate = s.response_rate()
            summary = s.summary()
        return render_template(
            "insights.html",
            title=cfg.dashboard_title,
            active="insights",
            per_week=per_week,
            counts=counts,
            response_rate=rate,
            summary=summary,
            profile=cfg.name,
        )

    # -- Actions ------------------------------------------------------------
    @app.route("/save/<dedup_key>", methods=["POST"])
    def toggle_save(dedup_key):
        saved = request.form.get("saved") == "1"
        with store() as s:
            s.set_saved(dedup_key, saved)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": True, "saved": saved})
        return redirect(request.referrer or url_for("jobs_view"))

    @app.route("/status/<key>/confirm", methods=["POST"])
    def confirm_status(key):
        # "Did we read this right?" — Yes keeps it, No hides it.
        decision = request.form.get("decision")
        confidence = "confirmed" if decision == "yes" else "rejected_by_user"
        with store() as s:
            s.set_status_confidence(key, confidence)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": True, "confidence": confidence})
        return redirect(request.referrer or url_for("jobs_view"))

    return app
