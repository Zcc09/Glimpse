"""Generate assets: multi-size .ico, PNG logo, and the self-test QR image.

Run:  .venv/Scripts/python.exe scripts/make_assets.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# the icons include font glyphs (the translate "A/ع" pair) — the offscreen Qt
# plugin draws text as garbage, so use the normal platform (no windows are shown)

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def write_ico(path: Path, entries: list[tuple[int, bytes]]) -> None:
    """Write a Vista+ ICO with PNG payloads (crisp per-size rendering)."""
    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    dir_entries = b""
    payload = b""
    for size, data in entries:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        dir_entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset + len(payload))
        payload += data
    path.write_bytes(header + dir_entries + payload)


def main() -> int:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtWidgets import QApplication

    from glimpse.icons import lens_pixmap

    app = QApplication([])  # noqa: F841
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)

    def png_of(size: int) -> bytes:
        pm = lens_pixmap(size)
        img = pm.toImage()
        ba = QByteArray()  # keep alive: QBuffer does not own it
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        return bytes(ba)

    for size in (512, 1024):
        lens_pixmap(size).save(str(assets / f"glimpse_{size}.png"), "PNG")

    write_ico(assets / "glimpse.ico", [(s, png_of(s)) for s in ICO_SIZES])

    import qrcode

    qr = qrcode.make("https://example.com/glimpse-selftest")
    qr.save(str(assets / "test_qr.png"))

    print(f"assets written to {assets}")
    for f in sorted(assets.iterdir()):
        if f.is_file():
            print(f"  {f.name}  {f.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
