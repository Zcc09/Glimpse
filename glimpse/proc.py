"""Subprocess helpers that never let a child console window flash on screen.

A PyInstaller ``--windowed`` app has no console of its own, so *every* console program it
runs — tesseract (once per OCR pass), ffmpeg, ffprobe — gets a brand-new console **window**
unless it is explicitly told not to. With the multi-pass OCR chain that becomes a storm of
flickering windows while the user waits for a translation, which looks exactly like a bug.

Everything the app shells out to goes through here.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Sequence

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)
STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
SW_HIDE = getattr(subprocess, "SW_HIDE", 0)


def hidden_kwargs() -> dict[str, Any]:
    """Popen kwargs that guarantee the child gets no console window."""
    kw: dict[str, Any] = {"creationflags": CREATE_NO_WINDOW}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= STARTF_USESHOWWINDOW
        si.wShowWindow = SW_HIDE
        kw["startupinfo"] = si
    return kw


def _merged(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Caller kwargs with the no-window flags merged in (never dropped)."""
    extra = int(kwargs.pop("creationflags", 0) or 0)
    kw = dict(kwargs)
    kw["creationflags"] = CREATE_NO_WINDOW | extra
    if os.name == "nt" and "startupinfo" not in kw:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= STARTF_USESHOWWINDOW
        si.wShowWindow = SW_HIDE
        kw["startupinfo"] = si
    return kw


def run(cmd: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    """``subprocess.run`` with no console window."""
    return subprocess.run(cmd, **_merged(kwargs))


def popen(cmd: Sequence[str], **kwargs) -> subprocess.Popen:
    """``subprocess.Popen`` with no console window."""
    return subprocess.Popen(cmd, **_merged(kwargs))
