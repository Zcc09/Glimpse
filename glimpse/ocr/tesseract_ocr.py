"""Tesseract engine: the bundled binary (vendor/tesseract) with on-demand language data."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtGui import QImage

from ..log import log
from ..paths import resource_path
from . import OcrError, OcrResult, _prepare_png

_COMMON = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def find_tesseract() -> str | None:
    """Bundled copy first (frozen: tesseract/, dev: vendor/tesseract/), then PATH, then installs."""
    for rel in ("tesseract/tesseract.exe", "vendor/tesseract/tesseract.exe"):
        try:
            cand = Path(resource_path(rel))
            if cand.is_file():
                return str(cand)
        except Exception:
            pass
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
            raise OcrError("Tesseract is not available (no bundled engine and none on PATH)")
        self.workdir = str(Path(self.exe).parent)

    def _run(self, png: bytes, langs: str, tessdata: Path, psm: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(png)
            proc = subprocess.run(
                [self.exe, path, "stdout", "-l", langs, "--tessdata-dir", str(tessdata), "--psm", psm],
                capture_output=True,
                timeout=90,
                check=False,
                cwd=self.workdir,  # so the engine finds its own DLLs
            )
            out = proc.stdout.decode("utf-8", "replace").strip()
            if proc.returncode != 0 and not out:
                err = proc.stderr.decode("utf-8", "replace")[:300]
                raise OcrError(f"tesseract failed: {err}")
            return out
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def recognize(self, image: QImage, languages=None) -> OcrResult:
        from . import languages as langdata
        from . import prepare_variants, score_text

        langdata.ensure_bundled()
        tessdata = langdata.tessdata_dir()

        wanted = [str(c) for c in (languages or ["eng"]) if c] or ["eng"]
        have = [c for c in wanted if (tessdata / f"{c}.traineddata").is_file()]
        missing = [c for c in wanted if c not in have]
        if missing:
            log.info(
                "tesseract: skipping languages without data (%s) — download them in Options → Text",
                ", ".join(missing),
            )
        if not have:
            raise OcrError(
                "no Tesseract language data installed — download a language in Options → Text"
            )

        langs = "+".join(have)
        best_text, best_score = "", -1.0
        for variant in prepare_variants(image):
            png = _prepare_png(variant)
            for psm in ("6", "3"):  # a single block suits a snip; auto layout as backup
                text = self._run(png, langs, tessdata, psm)
                s = score_text(text)
                if s > best_score:
                    best_text, best_score = text, s
                if best_score >= 60.0:  # a long, clean read is good enough
                    break
            if best_score >= 60.0:
                break
        log.debug("tesseract OCR: %d chars (%s, score %.1f)", len(best_text), langs, best_score)
        return OcrResult(text=best_text, lines=[], language=langs, engine="tesseract")
