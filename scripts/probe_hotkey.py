"""Probe: does synthetic keybd_event input trigger our RegisterHotKey + Qt filter?

Run in one shell:  .venv/Scripts/python.exe scripts/probe_hotkey.py
Then from another shell (within 20 s):
  .venv/Scripts/python.exe -c "import ctypes,time; u=ctypes.windll.user32; \
[ (u.keybd_event(v,0,0,0), time.sleep(0.03)) for v in (0x11,0x12,0x4C) ]; time.sleep(0.1); \
[ (u.keybd_event(v,0,2,0), time.sleep(0.03)) for v in (0x4C,0x12,0x11) ]"
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GLIMPSE_HOME", os.path.join(os.environ.get("TEMP", "."), "hk_probe"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from glimpse.hotkeys import HotkeyManager

OUT = os.path.join(os.environ.get("TEMP", "."), "hk_probe_result.txt")


def main() -> int:
    post_mode = "--post" in sys.argv
    app = QApplication([])
    sink = QWidget()
    sink.setWindowTitle("GlimpseHotkeySink")  # the same title the real app uses
    sink.resize(1, 1)
    mgr = HotkeyManager(int(sink.winId()))
    errors = mgr.set_hotkeys({"capture": "Ctrl+Alt+L", "translate": "Ctrl+Alt+T"})
    print("registration errors:", errors, flush=True)
    app.installNativeEventFilter(mgr)

    result = {"fired": None}

    def fired(action: str) -> None:
        result["fired"] = action
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(f"FIRED {action} at {time.time()}\n")
        print(f"FIRED {action}", flush=True)
        app.quit()

    mgr.triggered.connect(fired)

    if post_mode:
        # simulate the OS delivering WM_HOTKEY to the sink window (id 1 = capture)
        import ctypes

        def post():
            hwnd = ctypes.windll.user32.FindWindowW(None, "GlimpseHotkeySink")
            print("found sink hwnd:", hwnd, flush=True)
            ctypes.windll.user32.PostMessageW(hwnd, 0x0312, 1, 0)

        QTimer.singleShot(900, post)
        QTimer.singleShot(8000, app.quit)
    else:
        QTimer.singleShot(20000, app.quit)

    print(f"listening ({'post mode' if post_mode else 'key injection mode'})…", flush=True)
    app.exec()

    if result["fired"] is None:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("NO-EVENT\n")
        print("NO-EVENT: the hotkey never reached the manager", flush=True)
        return 1
    print(f"OK: hotkey fired '{result['fired']}'", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
