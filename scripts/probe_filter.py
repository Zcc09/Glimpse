"""Probe: which native events reach a PySide6 QAbstractNativeEventFilter, and how."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer
from PySide6.QtWidgets import QApplication, QWidget


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class F(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self.seen = 0

    def nativeEventFilter(self, etype, message):  # noqa: N802
        self.seen += 1
        try:
            et = bytes(etype).decode("utf-8", "replace") if isinstance(etype, (bytes, bytearray)) else str(etype)
        except Exception:
            et = repr(etype)
        n = 0
        tried = []
        for how in ("int()", "toint()", ".toint()"):
            try:
                if how == "int()":
                    n = int(message)
                elif how == "toint()":
                    n = message.toint()
                else:
                    n = message.toint()
                tried.append(f"{how}->{n}")
                if n:
                    break
            except Exception as e:
                tried.append(f"{how}:{type(e).__name__}")
        info = ""
        if n:
            try:
                m = MSG.from_address(n)
                info = f"msg=0x{m.message:04X} wParam={m.wParam} hwnd={m.hwnd}"
            except Exception as e:
                info = f"MSG read failed: {e}"
        if self.seen <= 25 or "MSG" in info:
            print(f"[{self.seen}] et={et!r} {'/'.join(tried)} {info}", flush=True)
        return False


def main() -> int:
    app = QApplication([])
    sink = QWidget()
    sink.setWindowTitle("GlimpseFilterProbe")
    sink.resize(1, 1)
    hwnd = int(sink.winId())
    print("sink hwnd:", hwnd, flush=True)
    f = F()
    app.installNativeEventFilter(f)

    def post():
        u = ctypes.windll.user32
        h = u.FindWindowW(None, "GlimpseFilterProbe")
        print("PostMessage →", h, flush=True)
        print("  result:", u.PostMessageW(h, 0x0312, 1, 0), flush=True)

    QTimer.singleShot(800, post)
    QTimer.singleShot(4000, app.quit)
    app.exec()
    print(f"filter saw {f.seen} events", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
