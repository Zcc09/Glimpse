"""Tesseract engine: the bundled binary (vendor/tesseract) with on-demand language data.

Recognition is **multi-pass**: the languages the user ticked are tried first, then one
pass per *writing system* present in the installed language data (Han, Arabic, Cyrillic,
Devanagari, …). Every pass is ranked with Tesseract's own per-word confidence, so a
two-character Chinese snip is read by the Han model instead of being mangled by an
English-only pass — which is what "doesn't find the text" used to mean.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QImage

from ..log import log
from ..paths import resource_path
from . import OcrError, OcrResult, _prepare_png

_COMMON = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

RUN_TIMEOUT = 30  # seconds per pass
_CONFIDENT_RANK = 92.0  # stop searching once a pass is this sure of itself
_TIME_BUDGET = 15.0  # never spend longer than this on one snip, whatever it contains
_LAST_WINNER: dict[str, list[str] | None] = {"langs": None}


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


@dataclass
class _Pass:
    """One Tesseract run over one set of languages."""

    langs: list[str]
    text: str = ""
    words: list[tuple[float, str]] = field(default_factory=list)  # (confidence, word)

    @property
    def mean_conf(self) -> float:
        confs = [c for c, _ in self.words]
        return sum(confs) / len(confs) if confs else 0.0

    @property
    def confident_words(self) -> int:
        return sum(1 for c, _ in self.words if c >= 60)

    @property
    def rank(self) -> float:
        """How much to trust this pass.

        Confidence, discounted when the text is in the *wrong* script for these
        languages (a Cyrillic model reading Greek looks confident), when it is full of
        misread tokens, and weighted by how much was read — a single lucky glyph must
        not beat a fully-read line.
        """
        from . import junk_ratio
        from .languages import script_consistency

        consistency = script_consistency(self.text, self.langs)
        base = self.mean_conf * (0.45 + 0.55 * consistency)
        return base + min(12.0, 2.0 * self.confident_words) - 25.0 * junk_ratio(self.text)


class TesseractOcr:
    def __init__(self, exe: str | None = None):
        self.exe = exe or find_tesseract()
        if not self.exe:
            raise OcrError("Tesseract is not available (no bundled engine and none on PATH)")
        self.workdir = str(Path(self.exe).parent)

    # ------------------------------------------------------------ one pass
    def _run(self, png: bytes, langs: str, tessdata: Path, psm: str) -> list[tuple[float, str]]:
        """Run Tesseract and return [(confidence, word), …] from its TSV output."""
        fd, path = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(png)
            proc = subprocess.run(
                [
                    self.exe, path, "stdout", "-l", langs, "--tessdata-dir", str(tessdata),
                    "--psm", psm, "-c", "tessedit_create_tsv=1",
                ],
                capture_output=True,
                timeout=RUN_TIMEOUT,
                check=False,
                cwd=self.workdir,  # so the engine finds its own DLLs
            )
            out = proc.stdout.decode("utf-8", "replace")
            if proc.returncode != 0 and not out.strip():
                err = proc.stderr.decode("utf-8", "replace")[:200]
                raise OcrError(f"tesseract failed: {err}")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        words: list[tuple[float, str]] = []
        for line in out.splitlines()[1:]:
            fields = [f.strip() for f in line.split("\t")]
            if len(fields) < 12 or not fields[11]:
                continue
            try:
                conf = float(fields[10])
            except ValueError:
                continue
            if conf >= 0:  # -1 marks layout rows, not words
                words.append((conf, fields[11]))
        return words

    def _pass(self, png: bytes, langs: list[str], tessdata: Path, fix) -> _Pass:
        joined = "+".join(langs)
        words = self._run(png, joined, tessdata, "6")
        if not words:  # nothing at all: a single line / sparse text may need another layout
            words = self._run(png, joined, tessdata, "7")
        text = fix(" ".join(w for _, w in words))
        return _Pass(langs=list(langs), text=text, words=words)

    # ------------------------------------------------------------ the search
    def recognize(
        self,
        image: QImage,
        languages=None,
        all_installed: bool = True,
        max_passes: int = 10,
    ) -> OcrResult:
        from . import is_plausible, junk_ratio
        from . import languages as langdata
        from . import prepare_variants

        junk_ratio_of = junk_ratio

        langdata.ensure_bundled()
        tessdata = langdata.tessdata_dir()
        installed = langdata.installed_languages()
        if not installed:
            raise OcrError(
                "no Tesseract language data installed — download a language in Options → Text"
            )

        wanted = [str(c) for c in (languages or []) if c] or ["eng"]
        have = [c for c in wanted if c in set(installed)]
        missing = [c for c in wanted if c not in set(installed)]
        if missing:
            log.info(
                "tesseract: skipping languages without data (%s) — download them in Options → Text",
                ", ".join(missing),
            )

        if all_installed:
            passes = langdata.script_passes(installed, preferred=have or ["eng"])
        else:
            passes = [have or ([c for c in ("eng",) if c in installed] or installed[:1])]

        last = _LAST_WINNER.get("langs")
        if last and last in passes:
            passes = [last] + [p for p in passes if p != last]

        best: _Pass | None = None
        runs = 0
        deadline = time.monotonic() + _TIME_BUDGET
        for variant in prepare_variants(image):
            png = _prepare_png(variant)
            for langs in passes[:max_passes]:
                if runs >= max_passes or time.monotonic() > deadline:
                    break
                runs += 1
                try:
                    cand = self._pass(png, langs, tessdata, langdata.cjk_space_fix)
                except OcrError as e:
                    log.warning("tesseract pass %s failed: %s", "+".join(langs), e)
                    continue
                if best is None or cand.rank > best.rank:
                    best = cand
                if (
                    cand.rank >= _CONFIDENT_RANK
                    and is_plausible(cand.text)
                    and junk_ratio_of(cand.text) < 0.2
                ):
                    break  # this pass is sure of itself and reads clean
            if (
                best is not None
                and best.rank >= _CONFIDENT_RANK
                and is_plausible(best.text)
                and junk_ratio_of(best.text) < 0.2
            ):
                break

        if best is None:
            raise OcrError("tesseract read nothing")
        _LAST_WINNER["langs"] = best.langs
        log.debug(
            "tesseract OCR: %d chars via %s (conf %.1f, %d run(s))",
            len(best.text), "+".join(best.langs), best.mean_conf, runs,
        )
        return OcrResult(
            text=best.text,
            lines=[],
            language="+".join(best.langs),
            engine="tesseract",
            confidence=round(best.mean_conf, 1),
        )
