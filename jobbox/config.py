"""Configuration loading with two-profile support (e.g. parttime / fulltime).

Each profile is a YAML file under ``config/<profile>.yaml`` and describes a
single Gmail inbox: which senders to read, keywords to keep/exclude, the CV
keywords used for match scoring, and dashboard/digest presentation.

Secrets (OAuth client + token) are referenced by path so they can live outside
version control. Token paths default to being profile-specific so two Gmail
accounts never share credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

# Project root = parent of the jobbox package directory.
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
SECRETS_DIR = ROOT_DIR / "secrets"


@dataclass
class ProfileConfig:
    """Resolved configuration for a single inbox profile."""

    # Identity
    name: str
    dashboard_title: str = "JobBox"

    # Gmail OAuth files (paths). Each profile gets its own token so two Gmail
    # accounts can be authorised independently.
    credentials_file: str = "secrets/credentials.json"
    token_file: str = "secrets/token_{profile}.json"

    # Which senders/domains count as job alerts. Empty = accept all senders
    # and rely on keyword filtering instead.
    senders: List[str] = field(default_factory=list)

    # Keep a job only if the subject/body matches at least one of these
    # (case-insensitive). Empty = keep everything not excluded.
    keywords: List[str] = field(default_factory=list)

    # Drop a job if it matches any of these (case-insensitive).
    exclusions: List[str] = field(default_factory=list)

    # CV keywords used to compute a per-job match score (0-100).
    cv_keywords: List[str] = field(default_factory=list)

    # How many days back to scan Gmail on each sync.
    lookback_days: int = 30

    # A job posted within this many hours is flagged "early apply".
    early_apply_hours: int = 24

    def resolved_credentials_file(self) -> Path:
        return (ROOT_DIR / self.credentials_file).resolve()

    def resolved_token_file(self) -> Path:
        raw = self.token_file.replace("{profile}", self.name)
        return (ROOT_DIR / raw).resolve()

    def resolved_db_file(self) -> Path:
        return (DATA_DIR / f"jobbox_{self.name}.db").resolve()


def available_profiles() -> List[str]:
    """Return the names of configured profiles (config/<name>.yaml)."""
    if not CONFIG_DIR.exists():
        return []
    names = []
    for p in sorted(CONFIG_DIR.glob("*.yaml")):
        if p.name.endswith(".example.yaml"):
            continue
        names.append(p.stem)
    return names


def load_profile(profile: str) -> ProfileConfig:
    """Load and validate a profile config from ``config/<profile>.yaml``.

    Raises FileNotFoundError with a helpful message if the profile is missing.
    """
    path = CONFIG_DIR / f"{profile}.yaml"
    if not path.exists():
        existing = available_profiles()
        hint = (
            f"Available profiles: {', '.join(existing)}"
            if existing
            else "No profiles found. Copy config/profile.example.yaml to "
            "config/parttime.yaml (and config/fulltime.yaml) and edit them."
        )
        raise FileNotFoundError(f"Config not found: {path}\n{hint}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    # Allow the file to omit "name"; fall back to the filename stem.
    raw.setdefault("name", profile)

    known = ProfileConfig.__dataclass_fields__.keys()
    filtered = {k: v for k, v in raw.items() if k in known}
    unknown = set(raw) - set(known)
    if unknown:
        # Non-fatal: warn so typos in config surface but don't crash the sync.
        print(f"[config] Warning: ignoring unknown keys in {path.name}: {sorted(unknown)}")

    cfg = ProfileConfig(**filtered)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return cfg


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, SECRETS_DIR):
        d.mkdir(parents=True, exist_ok=True)
