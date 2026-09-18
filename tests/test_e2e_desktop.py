"""Live desktop E2E: drives the REAL app the way a user does.

Synthetic input (Windows keybd/mouse events) fires the real global hotkeys, drags a
real selection over a real window, and the assertions read what the app actually
produced (history DB, image files) — no mocks anywhere. These tests briefly open
windows on the desktop, so they are opt-in:

    pytest tests/test_e2e_desktop.py -m live_desktop -v
"""
from __future__ import annotations

import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from .helpers import ROOT, make_qr_image

user32 = ctypes.windll.user32

KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_RETURN = 0x0D
WM_HOTKEY = 0x0312
HOTKEY_IDS = {"capture": 1, "translate": 2, "visual": 3, "songid": 4, "record": 5}  # glimpse.hotkeys.FIXED_IDS

# must match glimpse/overlay.py
BAR_PAD, BTN_W, BTN_H, BAR_GAP, SEP_W, SEP_MARGIN, CLOSE_W = 8, 96, 46, 6, 1, 4, 40
ACTION_ORDER = ["text", "translate", "visual", "qr", "save", "record", "copy"]


# ------------------------------------------------------------------ input synth
def _key_down(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)


def _key_up(vk: int) -> None:
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def key_press(vk: int) -> None:
    _key_down(vk)
    time.sleep(0.04)
    _key_up(vk)


WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


_APP_PIDS: set[int] = set()  # pids owning the sink window(s) this session started


def _sink_pids() -> set[int]:
    """Every pid that currently owns a GlimpseHotkeySink window.

    A real Glimpse may already be running in the tray, so the harness diffs this set
    before and after launching its own app instead of guessing a pid (the venv's
    python.exe is a trampoline: the app's real pid is a child of the spawned one).
    """
    import ctypes.wintypes as wt

    rows: list[int] = []

    def cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 2)
        user32.GetWindowTextW(hwnd, buf, length + 2)
        if "GlimpseHotkeySink" in buf.value:
            owner = wt.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            rows.append(int(owner.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return set(rows)


def _find_sink_hwnd(timeout: float = 6.0, pids: set[int] | None = None):
    """Find the sink window of *the app this test started*."""
    import ctypes.wintypes as wt

    want = pids if pids is not None else _APP_PIDS
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        def cb(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 2)
            user32.GetWindowTextW(hwnd, buf, length + 2)
            if "GlimpseHotkeySink" not in buf.value:
                return True
            owner = wt.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if not want or int(owner.value) in want:
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def post_hotkey(action: str) -> None:
    """Fire a real WM_HOTKEY at the app's hotkey sink window.

    NOTE: injected keybd_event/SendInput input does NOT match RegisterHotKey
    hotkeys on Windows 11, so the OS-level key matching itself is verified by a
    human pressing the combination; everything from the hotkey handler onwards
    is exercised here for real (same message, same window, same code path).
    """
    hwnd = _find_sink_hwnd()
    assert hwnd, "Glimpse hotkey sink window not found"
    assert user32.PostMessageW(hwnd, WM_HOTKEY, HOTKEY_IDS[action], 0), "PostMessage failed"


def drag(x0: int, y0: int, x1: int, y1: int, steps: int = 14) -> None:
    user32.SetCursorPos(x0, y0)
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    for i in range(1, steps + 1):
        user32.SetCursorPos(int(x0 + (x1 - x0) * i / steps), int(y0 + (y1 - y0) * i / steps))
        time.sleep(0.03)
    time.sleep(0.15)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def click(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def action_bar_button_offset(action: str) -> int:
    idx = ACTION_ORDER.index(action)
    return BAR_PAD + idx * (BTN_W + BAR_GAP) + BTN_W // 2


BAR_H = BTN_H + BAR_PAD * 2 + 2


# ------------------------------------------------------------------ app harness
# The harness must not fight a real Glimpse that is already running in the tray: use a
# modifier combination the app never claims by default, so registration always succeeds.
TEST_HOTKEYS = {
    "capture": "Ctrl+Alt+F13",
    "translate": "Ctrl+Alt+F14",
    "visual": "Ctrl+Alt+F15",
    "songid": "Ctrl+Alt+F16",
    "record": "Ctrl+Alt+F17",
}


def _write_settings(home: Path, **overrides) -> None:
    settings = {
        "default_action": "text",
        "copy_image_on_capture": True,
        "save_history": True,
        "history_limit": 50,
        "show_toasts": False,
        "target_lang": "auto",
        "secondary_lang": "ar",
        "hotkeys": dict(TEST_HOTKEYS),
    }
    settings.update(overrides)
    (home / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


def _start_app(home: Path, exit_after: int = 90):
    global _APP_PIDS
    before = _sink_pids()
    env = os.environ.copy()
    env["GLIMPSE_HOME"] = str(home)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "glimpse", "--tray", "--exit-after", str(exit_after)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log = home / "glimpse.log"
    ready = f"hotkey registered: {TEST_HOTKEYS['capture']}"
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"app exited early (code {proc.returncode})")
        if log.exists() and ready in log.read_text(encoding="utf-8", errors="ignore"):
            _APP_PIDS = (_sink_pids() - before) or {proc.pid}
            return proc
        time.sleep(0.4)
    proc.kill()
    pytest.fail("app never registered its hotkeys")


def _stop_app(proc) -> None:
    global _APP_PIDS
    _APP_PIDS = set()
    # kill the whole tree: the venv's python.exe is a trampoline, so terminating only it
    # leaves the real app process running (and holding the hotkeys for the next test)
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()


def _wait(predicate, timeout: float, what: str):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.4)
    pytest.fail(f"timed out waiting for {what} (last={last!r})")


def _latest_entry(home: Path):
    db = home / "history.db"
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM entries ORDER BY ts DESC LIMIT 1").fetchall()
        con.close()
        return dict(rows[0]) if rows else None
    except Exception:
        return None


def _entry_of_kind(home: Path, kind: str):
    entry = _latest_entry(home)
    return entry if entry and entry.get("kind") == kind else None


def make_pattern_image(width: int = 1500, height: int = 1000):
    """A bright, static colour grid: pixels for the overlay test to measure against.

    Nothing on the desktop can change under it mid-drag, so a pixel comparison means
    something (a loading web page does not).
    """
    from PySide6.QtGui import QColor, QImage, QPainter

    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    palette = ["#e5484d", "#ffb224", "#46a758", "#0091ff", "#8e4ec6", "#12a594", "#d6409f", "#ff8b3d"]
    cols, rows = 8, 6
    cw, ch = width // cols, height // rows
    for r in range(rows):
        for c in range(cols):
            p.fillRect(c * cw + 6, r * ch + 6, cw - 12, ch - 12, QColor(palette[(r * cols + c) % len(palette)]))
    p.end()
    return img


def _show_text_window(app, text: str, width: int = 860, height: int = 160, x: int = 360, y: int = 300, pixel=44):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QLabel

    label = QLabel(text)
    label.setWindowFlags(
        Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
    )
    label.setStyleSheet("background: white; color: black;")
    font = QFont("Segoe UI")
    font.setPixelSize(pixel)
    font.setBold(True)
    label.setFont(font)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.resize(width, height)
    label.move(x, y)
    label.show()
    label.raise_()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)
    return label


def _show_image_window(app, image, x: int = 420, y: int = 320):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QLabel

    label = QLabel()
    label.setWindowFlags(
        Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
    )
    label.setStyleSheet("background: white;")
    pm = QPixmap.fromImage(image)
    label.setPixmap(pm)
    label.resize(pm.width() + 20, pm.height() + 20)
    label.move(x, y)
    label.show()
    label.raise_()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)
    return label


def _physical_rect(app, widget, inset: int = 8):
    dpr = app.primaryScreen().devicePixelRatio()
    tl = widget.mapToGlobal(widget.rect().topLeft())
    br = widget.mapToGlobal(widget.rect().bottomRight())
    return (
        int(tl.x() * dpr) + inset,
        int(tl.y() * dpr) + inset,
        int(br.x() * dpr) - inset,
        int(br.y() * dpr) - inset,
        dpr,
    )


# ------------------------------------------------------------------ tests
@pytest.mark.live_desktop
def test_overlay_paints_each_screen_1to1(app, tmp_path):
    """Inside the selection the screen must be pixel-identical to the freeze; outside dimmed.

    The samples are read off a static window this test owns, so nothing else on the
    desktop can change underneath them mid-drag. This is the mixed-DPI regression guard:
    the old picker was one window spanning every monitor and Windows scaled it to a
    single monitor's DPI, which made monitors at other scaling factors look zoomed in.
    """
    from glimpse.capture import grab_all

    home = tmp_path / "home"
    home.mkdir()
    _write_settings(home)

    pattern = make_pattern_image()
    window = _show_image_window(app, pattern, x=200, y=180)
    proc = _start_app(home)
    try:
        dpr = app.primaryScreen().devicePixelRatio()
        win_x, win_y = 210, 190                                  # inside the window frame
        sel = (500, 480, 1200, 880)                              # x0, y0, x1, y1 (logical)

        # sample points: on the pattern, inside the selection and outside it
        inside, outside = [], []
        for y in range(sel[1] + 40, sel[3] - 40, 120):
            for x in range(sel[0] + 40, sel[2] - 40, 200):
                inside.append((x, y))
        for y in range(win_y + 60, sel[1] - 60, 120):
            for x in range(win_x + 60, sel[2] - 40, 200):
                outside.append((x, y))
        assert len(inside) >= 4 and len(outside) >= 3, "not enough sample points"

        base = grab_all()
        base_img = base.pieces[0].pixmap.toImage()

        def px(img, x_logical, y_logical):
            return img.pixelColor(int(x_logical * dpr), int(y_logical * dpr))

        def lum(c):
            return (c.red() + c.green() + c.blue()) / 3.0

        time.sleep(0.4)
        post_hotkey("capture")
        time.sleep(1.8)
        drag(int(sel[0] * dpr), int(sel[1] * dpr), int(sel[2] * dpr), int(sel[3] * dpr))
        time.sleep(1.2)                                          # overlay repaints the selection

        after_img = grab_all().pieces[0].pixmap.toImage()

        def close_enough(x, y, tol=26):
            a, b = px(base_img, x, y), px(after_img, x, y)
            return abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol and abs(a.blue() - b.blue()) <= tol

        matched = sum(1 for x, y in inside if close_enough(x, y))
        assert matched >= len(inside) - 1, (
            f"the selection must show the frozen screen 1:1 ({matched}/{len(inside)} matched)"
        )

        dimmed = sum(1 for x, y in outside if lum(px(after_img, x, y)) < lum(px(base_img, x, y)) * 0.85)
        assert dimmed >= len(outside) // 2, (
            f"everything outside the selection must be dimmed ({dimmed}/{len(outside)})"
        )

        key_press(0x1B)  # Esc cancels the overlay
        time.sleep(0.8)
    finally:
        window.hide()
        _stop_app(proc)


@pytest.mark.live_desktop
def test_hotkey_capture_ocr_end_to_end(app, tmp_path):
    """Capture hotkey → drag → Enter must OCR the selection and store it in history."""
    home = tmp_path / "home"
    home.mkdir()
    _write_settings(home)
    label = _show_text_window(app, "Glimpse Desktop E2E 9090")
    proc = _start_app(home)
    try:
        x0, y0, x1, y1, _dpr = _physical_rect(app, label)
        time.sleep(0.5)
        post_hotkey("capture")
        time.sleep(1.8)                      # freeze-frame grab + overlay
        drag(x0, y0, x1, y1)
        time.sleep(1.0)                      # action bar appears
        key_press(VK_RETURN)                 # default action = Text
        entry = _wait(lambda: _latest_entry(home), 30, "a history entry")
        assert entry["kind"] == "text", entry
        text = (entry["text"] or "").lower()
        assert "glimpse" in text and "9090" in text, f"ocr text: {entry['text']!r}"
        assert Path(entry["image_path"]).exists(), "captured image missing"
        assert Path(entry["image_path"]).stat().st_size > 1000
    finally:
        _stop_app(proc)
        label.close()


@pytest.mark.live_desktop
@pytest.mark.network
def test_hotkey_translate_end_to_end(app, tmp_path):
    """Translate hotkey (Ctrl+Alt+T) must OCR and translate the selection with no further input."""
    home = tmp_path / "home"
    home.mkdir()
    _write_settings(home)
    label = _show_text_window(app, "Good morning my friend")
    proc = _start_app(home)
    try:
        x0, y0, x1, y1, _dpr = _physical_rect(app, label)
        time.sleep(0.5)
        post_hotkey("translate")
        time.sleep(1.8)
        drag(x0, y0, x1, y1)
        entry = _wait(lambda: _entry_of_kind(home, "translate"), 45, "a translate entry")
        extra = json.loads(entry["extra"] or "{}")
        translation = extra.get("translation") or ""
        assert any("\u0600" <= c <= "\u06FF" for c in translation), f"no arabic translation: {translation!r}"
        assert "good" in (entry["text"] or "").lower(), entry["text"]
    finally:
        _stop_app(proc)
        label.close()


@pytest.mark.live_desktop
def test_action_bar_code_button_end_to_end(app, tmp_path):
    """Selecting a QR code and clicking the 'Code' button must decode it."""
    home = tmp_path / "home"
    home.mkdir()
    _write_settings(home)
    payload = "https://example.com/glimpse-e2e-code"
    window = _show_image_window(app, make_qr_image(payload, size=420), x=500, y=340)
    proc = _start_app(home)
    try:
        x0, y0, x1, y1, dpr = _physical_rect(app, window, inset=24)
        time.sleep(0.5)
        post_hotkey("capture")
        time.sleep(1.8)
        drag(x0, y0, x1, y1)
        time.sleep(1.0)
        # click the "Code" button on the action bar (bar sits 10 logical px below the selection)
        sel_left_logical = round(x0 / dpr)
        sel_bottom_logical = round(y1 / dpr)
        bx = round((sel_left_logical + action_bar_button_offset("qr")) * dpr)
        by = round((sel_bottom_logical + 10 + BAR_H // 2) * dpr)
        click(bx, by)
        entry = _wait(lambda: _entry_of_kind(home, "qr"), 30, "a qr entry")
        assert payload in (entry["text"] or ""), entry["text"]
    finally:
        _stop_app(proc)
        window.close()
