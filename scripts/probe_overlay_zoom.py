"""Prove the per-screen overlay renders each monitor 1:1 (no cross-DPI zoom)."""
from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

faulthandler.enable()
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glimpse.capture import grab_all  # noqa: E402
from glimpse.overlay import Overlay  # noqa: E402

app = QApplication([])
print("grab…", flush=True)
shot = grab_all()
print(f"grabbed {len(shot.pieces)} screen(s)", flush=True)
ov = Overlay(shot, default_action="text")
print(f"overlay has {len(ov.windows)} window(s)", flush=True)

print("=== geometry/dpr per window ===", flush=True)
all_ok = True
for s in app.screens():
    win = next((w for w in ov.windows if w.piece.rect == s.geometry()), None)
    ok = win is not None and win.devicePixelRatio() == s.devicePixelRatio() and win.geometry() == s.geometry()
    print(f"  {s.name():16s} win={win.geometry().getRect() if win else None} screen={s.geometry().getRect()} "
          f"dpr={win.devicePixelRatio() if win else '-'}/{s.devicePixelRatio()} {'OK' if ok else 'FAIL'}", flush=True)
    all_ok = all_ok and ok

print("=== render each window into its own-device-size image ===", flush=True)
for i, w in enumerate(list(ov.windows)):
    rect = w.piece.rect
    dpr = w.piece.dpr
    dev_w, dev_h = round(rect.width() * dpr), round(rect.height() * dpr)
    canvas = QImage(dev_w, dev_h, QImage.Format.Format_RGB32)
    canvas.setDevicePixelRatio(dpr)
    canvas.fill(0)
    print(f"  [{i}] {rect.getRect()} dev={dev_w}x{dev_h} dpr={dpr} — rendering…", flush=True)
    w.render(canvas)
    print(f"  [{i}] rendered ok", flush=True)
    src = w.piece.pixmap.toImage()
    probe_dev = QPoint(int(dev_w * 0.62), int(dev_h * 0.41))
    a = src.pixelColor(probe_dev)
    b = canvas.pixelColor(probe_dev)
    delta = sum(abs(x - y) for x, y in zip((a.red(), a.green(), a.blue()), (b.red(), b.green(), b.blue())))
    dimmed_ok = sum((b.red(), b.green(), b.blue())) < sum((a.red(), a.green(), a.blue())) + 12  # dim overlay only darkens
    print(f"  [{i}] frozen={a.name()} rendered={b.name()} delta={delta} {'OK (dimmed)' if dimmed_ok else 'MISMATCH'}", flush=True)

print("=== selection readback on screen 0 (logical-size render, compare 1:1) ===", flush=True)
w0 = ov.windows[0]
ov._start = w0.piece.rect.topLeft() + QPoint(200, 200)
ov._end = w0.piece.rect.topLeft() + QPoint(700, 500)
sel = ov.selection_global()
print(f"  selection {sel.getRect()}", flush=True)
dpr0 = w0.piece.dpr
# Qt 6.11 crashes when a hidden DPR-1.5 window is rendered into a canvas smaller than
# its device size, so use the device size; the widget paints at logical scale into it
shot_img = QImage(round(w0.width() * dpr0), round(w0.height() * dpr0), QImage.Format.Format_RGB32)
shot_img.fill(0)
w0.render(shot_img)
src0 = w0.piece.pixmap.toImage()
print(f"  rendered {shot_img.width()}x{shot_img.height()} logical, frozen {src0.width()}x{src0.height()} device (dpr {dpr0})", flush=True)
mismatch = 0
checked = 0
for dx in (30, 150, 300):
    for dy in (30, 120, 250):
        lp = QPoint(200 + dx, 200 + dy)                       # logical, inside the selection
        dev = QPoint(round(lp.x() * dpr0), round(lp.y() * dpr0))
        a = src0.pixelColor(dev)
        b = shot_img.pixelColor(lp)
        checked += 1
        if sum(abs(x - y) for x, y in zip((a.red(), a.green(), a.blue()), (b.red(), b.green(), b.blue()))) > 40:
            mismatch += 1
# a point outside the selection must be dimmed (proves the overlay is really drawn)
out_lp = QPoint(1500, 900)
out_src = src0.pixelColor(round(out_lp.x() * dpr0), round(out_lp.y() * dpr0))
out_got = shot_img.pixelColor(out_lp)
dimmed = sum((out_got.red(), out_got.green(), out_got.blue())) < sum((out_src.red(), out_src.green(), out_src.blue()))
print(f"  inside-selection samples: {checked}, mismatches={mismatch}", flush=True)
print(f"  outside sample: frozen={out_src.name()} on-screen={out_got.name()} dimmed={dimmed}", flush=True)

print("closing…", flush=True)
ov.close()
del ov
print("RESULT:", "PASS" if (all_ok and mismatch == 0 and dimmed) else "FAIL", flush=True)
