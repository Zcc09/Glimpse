"""Small shared helpers: background task runner, text utilities, clipboard/qimage helpers."""
from __future__ import annotations

import re
import threading
import traceback
from typing import Callable, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal

from .log import log

# ------------------------------------------------------------------ background tasks
class _Sig(QObject):
    ok = Signal(object)
    err = Signal(str, str, str)


_live: set[_Sig] = set()


def run_bg(
    fn: Callable[[], object],
    on_ok: Optional[Callable[[object], None]] = None,
    on_err: Optional[Callable[[str, str, str], None]] = None,
    name: str = "task",
) -> None:
    """Run fn() on a worker thread; deliver the result on the Qt main thread."""
    sig = _Sig()
    _live.add(sig)

    def _finish() -> None:
        _live.discard(sig)
        sig.deleteLater()

    def _emit_ok(res: object) -> None:
        try:
            if on_ok:
                on_ok(res)
        finally:
            _finish()

    def _emit_err(kind: str, msg: str, tb: str) -> None:
        try:
            if on_err:
                on_err(kind, msg, tb)
        finally:
            _finish()

    sig.ok.connect(_emit_ok)
    sig.err.connect(_emit_err)

    def _work() -> None:
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            log.error("background task %s failed: %s: %s\n%s", name, type(e).__name__, e, tb)
            sig.err.emit(type(e).__name__, str(e), tb)
        else:
            sig.ok.emit(res)

    threading.Thread(target=_work, daemon=True, name=f"glimpse-{name}").start()


# ------------------------------------------------------------------ text utils
_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def contains_arabic(text: str) -> bool:
    if not text:
        return False
    hits = len(_ARABIC.findall(text))
    letters = sum(1 for c in text if c.isalpha())
    return hits > 0 and (letters == 0 or hits / max(letters, 1) >= 0.15)


_MATH_WORDS = ("sqrt", "cbrt", "pi", "sin", "cos", "tan", "log", "ln", "exp", "abs")
_MATH_CHARS = re.compile(r"^[\d\s\.\+\-\*/\(\)\[\]\{\}\^%×÷=√π,]+$")


def looks_like_math(text: str) -> bool:
    """True when the text looks like an expression worth sending to WolframAlpha."""
    t = (text or "").strip()
    if not t or len(t) > 160 or not re.search(r"[0-9]", t):
        return False
    if not re.search(r"[+\-*/^=×÷√]", t):
        return False
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if len(lines) > 3:
        return False
    stripped = t.lower()
    for word in _MATH_WORDS:
        stripped = stripped.replace(word, "")
    stripped = stripped.replace("x", "")  # common variable
    return bool(_MATH_CHARS.match(stripped))


def shorten(text: str, n: int = 80) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


# ------------------------------------------------------------------ images / clipboard
def png_bytes(image) -> bytes:
    """QImage → PNG bytes.

    NOTE: the QByteArray must be kept alive in a Python variable — passing a
    temporary to QBuffer leaves Qt writing into freed memory (crash on Qt 6.11).
    """
    from PySide6.QtGui import QImage

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    fmt = "PNG"
    if not image.save(buf, fmt):
        image.convertToFormat(QImage.Format.Format_RGB32).save(buf, fmt)
    buf.close()
    return bytes(ba)


def qimage_from_bytes(data: bytes):
    from PySide6.QtGui import QImage

    img = QImage()
    img.loadFromData(data)
    return img


def copy_text(text: str) -> None:
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText(text or "")


def copy_image(image) -> None:
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setImage(image)


def open_url(url: str) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    try:
        return bool(QDesktopServices.openUrl(QUrl(url)))
    except Exception:
        import webbrowser

        return webbrowser.open(url)


def open_path(path: str) -> bool:
    import os

    try:
        os.startfile(path)  # noqa: S606 (windows)
        return True
    except Exception:
        return open_url("file:///" + str(path).replace("\\", "/"))
