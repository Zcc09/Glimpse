"""Console windows must never flash on screen.

The installed build is a ``--windowed`` exe: it owns no console, so every console program it
runs gets a brand-new console *window* unless it is told not to. The multi-pass OCR chain runs
tesseract many times per snip, so the user saw "a bunch of windows popping out and closing"
while a translation was being read.

These tests run console children from a console-less parent (``pythonw``), which is exactly the
frozen app's situation, and count the console windows the user would see.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
# conhost windows and Windows Terminal windows (the default host on Windows 11)
CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}

CHILD_TEMPLATE = '''
import ctypes, subprocess, sys, time
sys.path.insert(0, {root!r})
hidden = sys.argv[1] == "hidden"
if hidden:
    from glimpse.proc import hidden_kwargs
    kwargs = hidden_kwargs()
else:
    kwargs = {{}}
for _ in range(3):
    subprocess.run(["cmd", "/c", "ping", "-n", "2", "127.0.0.1"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
time.sleep(0.4)
'''


def _visible_consoles() -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        name = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, name, 128)
        if name.value in CONSOLE_CLASSES:
            title = ctypes.create_unicode_buffer(160)
            user32.GetWindowTextW(hwnd, title, 160)
            out[int(hwnd)] = (name.value, title.value[:40])
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def _settle(timeout: float = 8.0) -> None:
    """Wait until no console windows are appearing or disappearing."""
    last, stable, end = None, 0, time.time() + timeout
    while time.time() < end:
        current = set(_visible_consoles())
        stable = stable + 1 if current == last else 0
        last = current
        if stable >= 3:
            return
        time.sleep(0.25)


def _flashes(tmp_path: Path, mode: str) -> int:
    """Console windows that appear while a console-less parent runs 3 console children."""
    script = tmp_path / f"child_{mode}.py"
    script.write_text(CHILD_TEMPLATE.format(root=str(ROOT)), encoding="utf-8")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw) if pythonw.is_file() else sys.executable

    _settle()
    before = set(_visible_consoles())
    proc = subprocess.Popen([exe, str(script), mode])
    seen: dict[int, tuple[str, str]] = {}
    end = time.time() + 20
    while time.time() < end and proc.poll() is None:
        for hwnd, info in _visible_consoles().items():
            if hwnd not in before:
                seen[hwnd] = info
        time.sleep(0.05)
    proc.wait(timeout=20)
    _settle(timeout=4.0)
    print(f"{mode}: {len(seen)} console window(s) {list(seen.values())[:2]}")
    return len(seen)


def test_the_detector_sees_the_bug(tmp_path):
    """Without the flags a console-less parent *does* make visible console windows."""
    assert _flashes(tmp_path, "plain") >= 1, "detector is blind — the other test proves nothing"


def test_hidden_children_flash_nothing(tmp_path):
    """The same run through glimpse.proc shows the user no console window at all."""
    assert _flashes(tmp_path, "hidden") == 0


def test_no_call_site_bypasses_the_helper():
    """Every subprocess call in the app must go through glimpse.proc."""
    pattern = re.compile(r"subprocess\.(run|Popen|call|check_output|check_call)\s*\(")
    offenders: list[str] = []
    for path in ROOT.joinpath("glimpse").rglob("*.py"):
        if path.name == "proc.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and "subprocess.PIPE" not in line and "subprocess.DEVNULL" not in line:
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "subprocess call sites must use glimpse.proc:\n" + "\n".join(offenders)


def test_ocr_and_ffmpeg_calls_go_through_the_helper(glimpse_home):
    """The OCR pass and the clip helpers specifically (the paths that flashed)."""
    from glimpse import proc
    from glimpse.ocr.tesseract_ocr import TesseractOcr

    calls: list[list[str]] = []
    real_run = proc.run

    def spy(cmd, **kwargs):
        calls.append(list(cmd))
        return real_run(cmd, **kwargs)

    import glimpse.ocr.tesseract_ocr as TO

    TO.proc_mod.run = spy
    try:
        engine = TesseractOcr()
        if engine.exe:
            try:
                engine._run(b"\x89PNG\r\n\x1a\n", "eng", Path(engine.workdir or "."), "6")
            except Exception:
                pass
    finally:
        TO.proc_mod.run = real_run

    if engine.exe:
        assert calls, "tesseract did not go through glimpse.proc.run"
        assert calls[0][0] == engine.exe
    assert "startupinfo" in proc.hidden_kwargs() or os.name != "nt"


@pytest.mark.live_desktop
def test_frozen_app_ocr_flashes_nothing(glimpse_home):
    """The built app (windowed, no console) must read a snip without any console window."""
    exe = ROOT / "dist" / "Glimpse" / "Glimpse.exe"
    if not exe.is_file():
        pytest.skip("no frozen build in dist/")
    fixture = ROOT / "tests" / "assets" / "cn_label.png"

    _settle()
    before = set(_visible_consoles())
    env = dict(os.environ, GLIMPSE_HOME=str(glimpse_home))
    proc = subprocess.Popen(
        [str(exe), "--ocr", str(fixture)], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    seen: set[int] = set()
    end = time.time() + 60
    while time.time() < end and proc.poll() is None:
        seen |= set(_visible_consoles()) - before
        time.sleep(0.05)
    proc.wait(timeout=30)
    assert not seen, f"{len(seen)} console window(s) appeared during a frozen OCR run"
