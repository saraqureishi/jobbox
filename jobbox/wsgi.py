"""WSGI entry point for deploying the dashboard (e.g. gunicorn jobbox.wsgi:app).

For a PUBLIC portfolio demo, this serves the ``demo`` profile so recruiters can
click around a live instance without any real Gmail data. Seed it first with:

    python -m jobbox.cli demo --profile demo

Never deploy this publicly pointed at a profile backed by a real Gmail token.
"""

from __future__ import annotations

import os

from .cli import _demo_cfg
from .config import available_profiles, load_profile
from .webapp import create_app

_PROFILE = os.environ.get("JOBBOX_PROFILE", "demo")

if _PROFILE in available_profiles():
    _cfg = load_profile(_PROFILE)
else:
    _cfg = _demo_cfg(_PROFILE)

app = create_app(_cfg)
