"""Shared test helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def render_text_image(text: str = "Glimpse pipeline 777", width: int = 760, height: int = 240, pointsize: int = 30):
    """Render black text on white — the same way the app renders, on the real platform."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    f = QFont("Segoe UI")
    f.setPointSize(pointsize)
    p.setFont(f)
    p.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


def make_qr_image(payload: str, size: int = 420):
    """Generate a QR code as a QImage (via qrcode + PIL, dev-only deps)."""
    import io

    import qrcode
    from PIL import Image
    from PySide6.QtGui import QImage

    qr = qrcode.make(payload)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    img = QImage()
    img.loadFromData(buf.getvalue())
    return img


def tone_wav(path: str, seconds: float = 8.0, freq: float = 440.0, rate: int = 44100) -> str:
    import math
    import struct
    import wave

    n = int(rate * seconds)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            frames += struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
        w.writeframes(bytes(frames))
    return path


def has_loopback() -> bool:
    try:
        import pyaudiowpatch as pyaudio

        pa = pyaudio.PyAudio()
        try:
            n = len(list(pa.get_loopback_device_info_generator()))
        finally:
            pa.terminate()
        return n > 0
    except Exception:
        return False
