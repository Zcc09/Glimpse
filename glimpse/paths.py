"""Filesystem locations for Glimpse.

GLIMPSE_HOME overrides the data dir (used by the test suite / portable mode).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import __app_name__


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    env = os.environ.get("GLIMPSE_HOME")
    if env:
        p = Path(env)
    else:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        p = Path(base) / __app_name__
    p.mkdir(parents=True, exist_ok=True)
    return p


def captures_dir() -> Path:
    d = app_dir() / "captures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> Path:
    return app_dir() / "settings.json"


def history_path() -> Path:
    return app_dir() / "history.db"


def log_path() -> Path:
    return app_dir() / "glimpse.log"


def resource_path(rel: str) -> Path:
    """Locate a bundled resource (works in dev and in a PyInstaller bundle)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        cand = base / rel
        if cand.exists():
            return cand
        return Path(sys.executable).parent / rel
    return Path(__file__).resolve().parent.parent / rel
