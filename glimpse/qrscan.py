"""QR / barcode decoding via zxing-cpp (works on the cropped QImage)."""
from __future__ import annotations

from PySide6.QtGui import QImage


def decode_codes(image: QImage) -> list[dict]:
    """Return [{'format': str, 'text': str}] for every code found (deduped)."""
    import numpy as np
    import zxingcpp

    img = image.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = img.width(), img.height()
    if w < 4 or h < 4:
        return []
    ptr = img.constBits()
    raw = bytes(ptr)
    stride = img.bytesPerLine()
    arr = np.frombuffer(raw, dtype=np.uint8, count=stride * h).reshape(h, stride)[:, :w]
    results = zxingcpp.read_barcodes(np.ascontiguousarray(arr))

    out: list[dict] = []
    seen: set[str] = set()
    for r in results:
        text = r.text or ""
        if not text and r.bytes:
            try:
                text = bytes(r.bytes).decode("utf-8", "replace")
            except Exception:
                text = ""
        if not text:
            continue
        key = text.strip()
        if key in seen:
            continue
        seen.add(key)
        out.append({"format": str(r.format), "text": text})
    return out
