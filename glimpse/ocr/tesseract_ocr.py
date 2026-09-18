"""Tesseract fallback (only used when tesseract.exe is installed)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from PySide6.QtGui import QImage

from ..log import log
from . import OcrError, OcrResult, _prepare_png

_COMMON = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def find_tesseract() -> str | None:
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for cand in _COMMON:
        if os.path.exists(cand):
            return cand
    return None


class TesseractOcr:
    def __init__(self, exe: str | None = None):
        self.exe = exe or find_tesseract()
        if not self.exe:
            raise OcrError("Tesseract not found")

    def recognize(self, image: QImage, language: str = "") -> OcrResult:
        png = _prepare_png(image)
        fd, path = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(png)
            langs = language or "eng"
            # tesseract wants ISO codes like eng+ara
            langs = langs.replace("-", "+").replace("en+US", "eng").replace("US", "")
            langs = langs or "eng"
            proc = subprocess.run(
                [self.exe, path, "stdout", "-l", langs, "--psm", "3"],
                capture_output=True,
                timeout=60,
                check=False,
            )
            text = proc.stdout.decode("utf-8", "replace").strip()
            if proc.returncode != 0 and not text:
                raise OcrError(f"tesseract failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
            log.debug("tesseract OCR: %d chars", len(text))
            return OcrResult(text=text, lines=[], language=langs, engine="tesseract")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
