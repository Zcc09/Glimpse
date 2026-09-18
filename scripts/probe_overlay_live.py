"""Diagnose the live overlay: what is actually on screen while a selection is up?"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from glimpse.capture import grab_all  # noqa: E402

app = QApplication([])

TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))
import tests.test_e2e_desktop as H  # noqa: E402

home = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "glimpse_overlay_probe"
import shutil  # noqa: E402

shutil.rmtree(home, ignore_errors=True)
home.mkdir(parents=True)
H._write_settings(home)

proc = H._start_app(home)
try:
    dpr = app.primaryScreen().devicePixelRatio()
    sel = (300, 300, 1600, 1100)
    base = grab_all()
    piece = base.pieces[0]
    base_img = piece.pixmap.toImage()

    time.sleep(0.4)
    H.post_hotkey("capture")
    time.sleep(2.0)
    H.drag(int(sel[0] * dpr), int(sel[1] * dpr), int(sel[2] * dpr), int(sel[3] * dpr))
    time.sleep(1.5)

    after = grab_all()
    a_img = after.pieces[0].pixmap.toImage()

    out_dir = ROOT / "vendor"
    out_dir.mkdir(exist_ok=True)
    a_img.save(str(out_dir / "_overlay_probe.png"))
    b_img = base_img
    print("saved screenshot:", out_dir / "_overlay_probe.png")

    def lum(img, x, y):
        c = img.pixelColor(int(x * dpr), int(y * dpr))
        return round((c.red() + c.green() + c.blue()) / 3.0, 1)

    rows = []
    for y in range(350, 1100, 125):
        row = []
        for x in range(350, 1600, 250):
            row.append(f"{x},{y}: {lum(b_img, x, y):5.1f} -> {lum(a_img, x, y):5.1f}")
        rows.append("   ".join(row))
    for r in rows:
        print(r)

    inside = [(x, y) for y in range(350, 1050, 60) for x in range(350, 1550, 60)]
    diffs = [abs(lum(b_img, x, y) - lum(a_img, x, y)) for x, y in inside]
    print(f"inside samples: {len(inside)}; <=24: {sum(1 for d in diffs if d <= 24)}; "
          f"median diff {sorted(diffs)[len(diffs) // 2]}")

    H.key_press(0x1B)
    time.sleep(0.6)
finally:
    H._stop_app(proc)
    print("done")
