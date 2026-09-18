"""Debug: start the app like the E2E does and enumerate Glimpse windows with their PIDs."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

home = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "glimpse_win_probe"
if home.exists():
    import shutil

    shutil.rmtree(home, ignore_errors=True)
home.mkdir(parents=True)
(home / "settings.json").write_text(
    json.dumps(
        {
            "hotkeys": {
                "capture": "Ctrl+Shift+Alt+L",
                "translate": "Ctrl+Shift+Alt+T",
                "visual": "Ctrl+Shift+Alt+S",
                "songid": "Ctrl+Shift+Alt+M",
                "record": "Ctrl+Shift+Alt+R",
            }
        }
    ),
    encoding="utf-8",
)

env = os.environ.copy()
env["GLIMPSE_HOME"] = str(home)
proc = subprocess.Popen(
    [sys.executable, "-u", "-m", "glimpse", "--tray", "--exit-after", "60"],
    cwd=str(ROOT),
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)
print("started pid:", proc.pid, "sys.executable:", sys.executable)

deadline = time.time() + 30
log = home / "glimpse.log"
while time.time() < deadline:
    if log.exists() and "hotkey registered" in log.read_text(encoding="utf-8", errors="ignore"):
        break
    time.sleep(0.4)
time.sleep(1.5)

rows = []


def cb(hwnd, _l):
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buf, length + 2)
    title = buf.value
    if "Glimpse" in title or "HotkeySink" in title:
        owner = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        visible = bool(user32.IsWindowVisible(hwnd))
        rows.append((int(hwnd), int(owner.value), visible, title))
    return True


user32.EnumWindows(WNDENUMPROC(cb), 0)
print(f"windows with 'Glimpse' in the title: {len(rows)} (expected app pid {proc.pid})")
for hwnd, pid, visible, title in rows:
    mark = "  <-- ours" if pid == proc.pid else ""
    print(f"  hwnd={hwnd} pid={pid} visible={visible} title={title!r}{mark}")

proc.terminate()
try:
    proc.wait(timeout=10)
except Exception:
    proc.kill()
print("done")
