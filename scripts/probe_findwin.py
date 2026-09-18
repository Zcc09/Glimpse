"""Probe: is a hidden Qt sink window findable from ANOTHER process?"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

user32 = ctypes.windll.user32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def list_windows(tag: str) -> list[tuple[int, str, str, bool]]:
    out: list[tuple[int, str, str, bool]] = []

    def cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 2)
        user32.GetWindowTextW(hwnd, buf, length + 2)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if "Glimpse" in buf.value or "Glimpse" in cls.value:
            out.append((hwnd, buf.value, cls.value, bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    print(f"[{tag}] windows with 'Glimpse' in title/class:", flush=True)
    for hwnd, title, cls, visible in out:
        print(f"  hwnd={hwnd} title={title!r} class={cls!r} visible={visible}", flush=True)
    hwnd = user32.FindWindowW(None, "GlimpseHotkeySink")
    print(f"[{tag}] FindWindowW -> {hwnd}", flush=True)
    return out


def main() -> int:
    if "--listen" in sys.argv:
        app = QApplication([])
        sink = QWidget()
        sink.setWindowTitle("GlimpseHotkeySink")
        sink.resize(1, 1)
        hwnd = int(sink.winId())
        print(f"listening: sink hwnd={hwnd}", flush=True)
        QTimer.singleShot(25000, app.quit)
        app.exec()
        return 0

    list_windows("other-process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
