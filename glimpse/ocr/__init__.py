"""OCR engines and dispatch.

- ``windows``   — Windows.Media.Ocr (built in). With no language given it runs every
  installed recognizer language and keeps the best-looking result, so any language
  pack the user has added is used automatically.
- ``tesseract`` — the bundled Tesseract 5 engine: 126 languages, data downloaded on
  demand into %APPDATA%/Glimpse/tessdata.
- ``auto``      — Windows first (fast, no data files); when the result doesn't look
  like text (e.g. Arabic text on a machine with only the English pack) Tesseract is
  tried with the user's languages and the better result wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from ..log import log


@dataclass
class OcrLine:
    text: str
    rect: QRect = field(default_factory=QRect)


@dataclass
class OcrResult:
    text: str
    lines: list[OcrLine] = field(default_factory=list)
    language: str = ""
    engine: str = "windows"
    low_confidence: bool = False
    confidence: float = 0.0  # engine-reported confidence (0 when the engine has none)


class OcrError(RuntimeError):
    pass


# ------------------------------------------------------------------ quality score
_GOOD_PUNCT = set(".,;:!?()[]{}'\"-–—/\\@#$%&*+=<>|~^_`°·’”“…«»،؛؟")


def score_text(text: str) -> float:
    """Rough plausibility score for an OCR result (higher = more like real text).

    Used to pick between languages and between engines: a wrong language usually
    yields fewer letters/digits, more stray symbols and fewer real words.
    """
    t = (text or "").strip()
    if not t:
        return 0.0
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return 0.0
    letters = sum(1 for c in chars if c.isalpha() or c.isdigit())
    weird = sum(1 for c in chars if not (c.isalpha() or c.isdigit() or c in _GOOD_PUNCT))
    words = [w for w in re.split(r"\s+", t) if w]
    good_words = sum(1 for w in words if sum(1 for c in w if c.isalnum()) >= 2)
    ratio = letters / len(chars)
    word_quality = good_words / len(words)
    return len(t) * (0.2 + ratio) * (0.3 + 0.7 * word_quality) - weird * 4.0


MIN_PLAUSIBLE = 16.0  # below this the result is treated as "probably not text"


def is_plausible(text: str) -> bool:
    """Is this OCR output believable? Short results count when they are clean."""
    t = (text or "").strip()
    if not t:
        return False
    if score_text(t) >= MIN_PLAUSIBLE:
        return True
    chars = [c for c in t if not c.isspace()]
    letters = sum(1 for c in chars if c.isalpha() or c.isdigit())
    return len(chars) <= 12 and letters / max(1, len(chars)) >= 0.9


_SYMBOLS = set(".,;:!?()[]{}'\"-–—/\\@#$%&*+=<>|~^_`°·’”“…«»،؛؟")


def _is_junk_word(w: str) -> bool:
    """A single token that looks like a misread: symbol soup, digits inside letters, cAse."""
    alnum = [c for c in w if c.isalnum()]
    if not alnum:
        return True
    symbols = sum(1 for c in w if not (c.isalnum() or c in _SYMBOLS))
    if symbols >= 2:
        return True
    letters = [c for c in w if c.isalpha()]
    has_digit = any(c.isdigit() for c in w)
    if letters and has_digit and len(w) > 2:
        return True
    if len(letters) >= 3:
        lower_upper = sum(1 for a, b in zip(letters, letters[1:]) if a.islower() and b.isupper())
        upper_lower = sum(1 for a, b in zip(letters, letters[1:]) if a.isupper() and b.islower())
        if lower_upper >= 2 or (lower_upper >= 1 and upper_lower >= 1 and len(letters) >= 5):
            return True
    return False


def junk_ratio(text: str) -> float:
    """Fraction of tokens that look like OCR garbage (1.0 for empty text).

    Windows OCR happily renders Cyrillic or CJK as confident-looking Latin noise
    ('noroaa ceroAHfl OTJIL,-11--lHafi.'), so "it read several words" is not enough
    to trust a result — this is the check the engine chain uses before stopping.
    """
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    if not words:
        return 1.0
    return sum(1 for w in words if _is_junk_word(w)) / len(words)


# ------------------------------------------------------------------ preparation
def _mean_luma(image: QImage) -> int:
    """Average brightness (0-255), sampled sparsely — cheap dark-mode detection."""
    img = image.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return 255
    ptr = bytes(img.constBits())
    stride = img.bytesPerLine()
    step_y, step_x = max(1, h // 32), max(1, w // 64)
    total = n = 0
    for y in range(0, h, step_y):
        row = ptr[y * stride : y * stride + w]
        for x in range(0, w, step_x):
            total += row[x]
            n += 1
    return total // max(1, n)


def _scaled(image: QImage, factor: float) -> QImage:
    from PySide6.QtCore import Qt

    return image.scaled(
        max(1, round(image.width() * factor)),
        max(1, round(image.height() * factor)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _invert(image: QImage) -> QImage:
    img = image.convertToFormat(QImage.Format.Format_RGB32).copy()
    img.invertPixels()
    return img


def prepare_variants(image: QImage) -> list[QImage]:
    """The crop plus the usual rescue attempts: extra upscale, dark-mode inversion."""
    variants = [image, _scaled(image, 1.8)]
    if _mean_luma(image) < 110:  # dark-mode UI: engines expect dark text on light
        variants = [_invert(image), image, _invert(_scaled(image, 1.8)), _scaled(image, 1.8)]
    return variants


def _prepare_png(image: QImage, min_side: int = 90, upscale_to: int = 1000, max_dim: int = 2500) -> bytes:
    """Upscale small/thin crops (helps OCR a lot), clamp huge ones, encode PNG."""
    from ..util import png_bytes

    img = image
    if img.format() != QImage.Format.Format_ARGB32:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return png_bytes(img)
    factor = 1.0
    short, long_ = min(w, h), max(w, h)
    if short < min_side:
        factor = min(5.0, min_side / short)
    if long_ * factor < upscale_to:
        factor = min(5.0, upscale_to / long_)
    if long_ * factor > max_dim:  # stay inside the engines' pixel budget
        factor = max(1.0, max_dim / long_)
    if abs(factor - 1.0) > 0.01:
        img = _scaled(img, factor)
    return png_bytes(img)


# ------------------------------------------------------------------ engines
def _windows(image: QImage, language: str = "") -> OcrResult:
    from .windows_ocr import recognize_windows, recognize_windows_multi

    if language:
        return recognize_windows(image, language)
    return recognize_windows_multi(image)


def _windows_best(image: QImage, language: str = "") -> OcrResult:
    """Windows engine with a dark-mode rescue: invert when the crop is dark."""
    candidates = [image]
    if _mean_luma(image) < 110:
        candidates.append(_invert(image))
    best: OcrResult | None = None
    best_score = -1.0
    error: Exception | None = None
    for cand in candidates:
        try:
            res = _windows(cand, language)
        except Exception as e:  # noqa: BLE001
            error = e
            continue
        s = score_text(res.text)
        if s > best_score:
            best, best_score = res, s
    if best is None:
        raise error or OcrError("Windows OCR failed")
    return best


def _tesseract(image: QImage, languages, all_installed: bool = True) -> OcrResult:
    from .tesseract_ocr import TesseractOcr

    return TesseractOcr().recognize(image, languages, all_installed=all_installed)


def recognize(
    image: QImage,
    language: str = "",
    engine: str = "auto",
    tess_languages=None,
    all_languages: bool = True,
) -> OcrResult:
    """OCR one image with the configured engine chain."""
    return _flag(  # results that read as gibberish get flagged for the UI to explain
        _recognize(image, language, engine, tess_languages, all_languages)
    )


def _flag(res: OcrResult) -> OcrResult:
    from . import is_plausible

    res.low_confidence = not is_plausible(res.text)
    return res


def _quality(res: OcrResult | None) -> tuple:
    """Ranking for the engine comparison: confidence first, then how text-like it reads."""
    if res is None:
        return (-1.0, -1.0)
    return (res.confidence, score_text(res.text))


def _recognize(
    image: QImage,
    language: str = "",
    engine: str = "auto",
    tess_languages=None,
    all_languages: bool = True,
) -> OcrResult:
    engine = (engine or "auto").lower()
    tess_langs = [str(c) for c in (tess_languages or []) if c] or ["eng"]

    if engine == "windows":
        return _windows_best(image, language)
    if engine == "tesseract":
        return _tesseract(image, tess_langs, all_languages)

    # auto: Windows (any installed language) first, Tesseract as the safety net
    win: OcrResult | None = None
    try:
        win = _windows_best(image, language)
    except Exception as e:  # noqa: BLE001
        log.info("auto OCR: Windows engine unavailable (%s)", e)
    win_score = score_text(win.text) if win else -1.0
    # "it read several words" is not proof: Windows renders foreign scripts as
    # confident Latin noise, so only stop early when the read also looks clean
    if win is not None and win_score >= 60.0 and junk_ratio(win.text) < 0.25:
        return win

    try:
        tess = _tesseract(image, tess_langs, all_languages)
    except Exception as e:  # noqa: BLE001
        if win is not None:
            if not is_plausible(win.text):
                log.info("auto OCR: tesseract unavailable too (%s)", e)
            return win
        raise OcrError(f"no OCR engine available ({e})") from e

    if win is None:
        return tess
    if not tess.text.strip():
        return win  # tesseract found nothing; Windows is all we have

    # Both engines answered. Windows reports no confidence, so rank by how clean each
    # read is first (a wrong-script read is confident-looking Latin noise), then by
    # believability, and only give the win to tesseract when it read clearly more.
    #
    # Strongest signal first: if tesseract read a script Windows has no language pack for
    # (Greek text on an English-only machine), Windows cannot have read that text at all —
    # its answer is a transliteration of the glyphs, not the text.
    from .languages import dominant_script, windows_scripts

    tess_script = dominant_script(tess.text)
    if tess_script and is_plausible(tess.text):
        if tess_script not in windows_scripts(available_languages()):
            return tess

    win_junk, tess_junk = junk_ratio(win.text), junk_ratio(tess.text)
    if tess_junk + 0.25 < win_junk:
        return tess
    if win_junk + 0.25 < tess_junk:
        return win
    win_ok, tess_ok = is_plausible(win.text), is_plausible(tess.text)
    if tess_ok != win_ok:
        return tess if tess_ok else win
    if score_text(tess.text) > score_text(win.text) * 1.25:
        return tess
    return win


# ------------------------------------------------------------------ capabilities
def available_languages() -> list[str]:
    """Windows recognizer languages (language packs installed in Windows)."""
    try:
        from .windows_ocr import available_languages as langs

        return langs()
    except Exception:
        return []


def tesseract_available() -> bool:
    try:
        from .tesseract_ocr import find_tesseract

        return bool(find_tesseract())
    except Exception:
        return False


def tesseract_languages_installed() -> list[str]:
    try:
        from .languages import ensure_bundled, installed_languages

        ensure_bundled()
        return installed_languages()
    except Exception:
        return []
