"""Command-line interface for JobBox.

Commands:
  jobbox sync   --profile parttime          Read Gmail, parse, store.
  jobbox demo   --profile parttime          Seed the DB with demo data (no Gmail).
  jobbox serve  --profile parttime           Launch the web dashboard.
  jobbox profiles                            List configured profiles.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import available_profiles, ensure_dirs, load_profile
from .pipeline import sync_profile


def _delete_db(cfg) -> None:
    """Delete a profile's database file so the next sync rebuilds it cleanly.

    Clears out any stale jobs/statuses detected by older code. Handles the
    case where the file is missing; warns clearly if it's locked (e.g. a
    server is still running and holding it open on Windows).
    """
    db = cfg.resolved_db_file()
    if not db.exists():
        print(f"[reset] No existing database at {db} (nothing to clear).")
        return
    try:
        db.unlink()
        print(f"[reset] Cleared old database: {db}")
    except PermissionError:
        print(
            f"[reset] ERROR: could not delete {db} — it looks like it's open.\n"
            f"[reset] Stop any running 'serve' (press Ctrl+C in that window / "
            f"close the dashboard) and try again."
        )
        raise SystemExit(1)


def _cmd_reset(args) -> int:
    """One-step clean rebuild: delete the DB, then re-sync from Gmail."""
    cfg = load_profile(args.profile)
    print(f"[reset] Profile '{cfg.name}' — clearing old data and re-syncing...")
    _delete_db(cfg)
    return _run_sync(cfg, args.max)


def _cmd_sync(args) -> int:
    cfg = load_profile(args.profile)
    if getattr(args, "clear", False):
        _delete_db(cfg)
    print(f"[sync] Profile '{cfg.name}' — reading Gmail (all tabs), lookback "
          f"{cfg.lookback_days} days...")
    return _run_sync(cfg, args.max)


def _run_sync(cfg, max_results) -> int:
    result = sync_profile(cfg, max_results=max_results)
    print(f"[sync] Emails read : {result.emails_read}")
    print(f"[sync] Jobs found  : {result.jobs_found}  (new: {result.jobs_new})")
    print(f"[sync] Statuses    : {result.statuses_found}  (new: {result.statuses_new})")
    print(f"[sync] Done. Run:  jobbox serve --profile {cfg.name}")
    return 0


def _cmd_demo(args) -> int:
    from .demo_data import demo_emails

    cfg = load_profile(args.profile) if args.profile in available_profiles() else _demo_cfg(args.profile)
    print(f"[demo] Seeding profile '{cfg.name}' with synthetic emails (no Gmail contacted)...")
    result = sync_profile(cfg, emails=demo_emails())
    print(f"[demo] Jobs new: {result.jobs_new}, statuses new: {result.statuses_new}")
    print(f"[demo] Now run:  jobbox serve --profile {cfg.name}")
    return 0


def _demo_cfg(profile: str):
    """Build an in-memory config if the user hasn't created one yet."""
    from .config import ProfileConfig

    ensure_dirs()
    return ProfileConfig(
        name=profile,
        dashboard_title=f"JobBox — {profile} (demo)",
        senders=[],
        keywords=[],
        exclusions=[],
        cv_keywords=["python", "sql", "snowflake", "data", "machine learning"],
        early_apply_hours=24,
    )


def _cmd_serve(args) -> int:
    from .webapp import create_app

    cfg = load_profile(args.profile) if args.profile in available_profiles() else _demo_cfg(args.profile)
    app = create_app(cfg)
    print(f"[serve] '{cfg.dashboard_title}' on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def _cmd_profiles(_args) -> int:
    profiles = available_profiles()
    if not profiles:
        print("No profiles configured. Copy config/profile.example.yaml to "
              "config/parttime.yaml and config/fulltime.yaml.")
        return 0
    print("Configured profiles:")
    for p in profiles:
        print(f"  - {p}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobbox", description="Private Gmail job-alert aggregator.")
    parser.add_argument("--version", action="version", version=f"jobbox {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Read Gmail and update the local DB.")
    p_sync.add_argument("--profile", required=True, help="Profile name (e.g. parttime, fulltime)")
    p_sync.add_argument("--max", type=int, default=500, help="Max emails to read")
    p_sync.add_argument("--clear", action="store_true",
                        help="Wipe stored jobs/statuses first (clean rebuild)")
    p_sync.set_defaults(func=_cmd_sync)

    p_reset = sub.add_parser(
        "reset", help="Clear stored data and re-sync in one step (clean rebuild).")
    p_reset.add_argument("--profile", required=True, help="Profile name")
    p_reset.add_argument("--max", type=int, default=500, help="Max emails to read")
    p_reset.set_defaults(func=_cmd_reset)

    p_demo = sub.add_parser("demo", help="Seed the DB with demo data (no Gmail).")
    p_demo.add_argument("--profile", default="demo", help="Profile name to seed")
    p_demo.set_defaults(func=_cmd_demo)

    p_serve = sub.add_parser("serve", help="Launch the web dashboard.")
    p_serve.add_argument("--profile", required=True, help="Profile name")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=5000)
    p_serve.add_argument("--debug", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_prof = sub.add_parser("profiles", help="List configured profiles.")
    p_prof.set_defaults(func=_cmd_profiles)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
