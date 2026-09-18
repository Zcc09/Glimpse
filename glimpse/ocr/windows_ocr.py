"""Windows.Media.Ocr engine (winsdk) — no extra installs needed."""
from __future__ import annotations

import asyncio

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from ..log import log
from . import OcrError, OcrLine, OcrResult, _prepare_png


def available_languages() -> list[str]:
    from winsdk.windows.media.ocr import OcrEngine

    return [l.language_tag for l in OcrEngine.available_recognizer_languages]


async def _win_ocr(png: bytes, language: str) -> tuple[str, list[OcrLine]]:
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = None
    if language:
        try:
            engine = OcrEngine.try_create_from_language(Language(language))
        except Exception:  # noqa: BLE001
            engine = None
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None and language and language != "en-US":
        engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        langs = [l.language_tag for l in OcrEngine.available_recognizer_languages]
        raise OcrError(
            "No Windows OCR language available. Add one in Settings → Time & language → "
            f"Language & region (OCR needs the language pack). Installed: {langs}"
        )

    result = await engine.recognize_async(bitmap)
    lines: list[OcrLine] = []
    for line in result.lines:
        rect = QRect()
        for word in line.words:
            b = word.bounding_rect
            r = QRect(int(b.x), int(b.y), int(b.width), int(b.height))
            rect = r if rect.isNull() else rect.united(r)
        lines.append(OcrLine(text=line.text, rect=rect))
    return "\n".join(l.text for l in lines), lines


def recognize_windows(image: QImage, language: str = "") -> OcrResult:
    png = _prepare_png(image)
    text, lines = asyncio.run(_win_ocr(png, language or ""))
    lang = language or "auto"
    log.debug("windows OCR: %d chars, %d lines", len(text), len(lines))
    return OcrResult(text=text, lines=lines, language=lang, engine="windows")


_last_good: dict[str, str | None] = {"lang": None}


def recognize_windows_multi(image: QImage, languages=None, max_languages: int = 8) -> OcrResult:
    """Run Windows OCR over every installed recognizer language; keep the best.

    Windows has one recognizer per installed language pack, so a snip in a script the
    user has no pack for reads as garbage; running them all and scoring the output
    picks the right one without the user having to choose.
    """
    from . import score_text

    langs = list(languages) if languages else available_languages()
    if not langs:
        raise OcrError(
            "No Windows OCR language is installed. Add one in Settings → Time & language → "
            "Language & region (include 'Optical character recognition'), or use the bundled "
            "Tesseract engine in Options → Text."
        )
    last = _last_good.get("lang")
    ordered = ([last] if last in langs else []) + [l for l in langs if l != last]

    best: OcrResult | None = None
    best_score = -1.0
    for tag in ordered[:max_languages]:
        try:
            res = recognize_windows(image, tag)
        except Exception as e:  # noqa: BLE001
            log.debug("windows OCR (%s) failed: %s", tag, e)
            continue
        res.language = tag
        s = score_text(res.text)
        if s > best_score:
            best, best_score = res, s
        if best_score >= 60.0:
            break  # a long, clean read — no reason to try the rest
    if best is None:
        raise OcrError("Windows OCR failed for every installed language")
    _last_good["lang"] = best.language
    log.debug("windows multi OCR: best=%s score=%.1f", best.language, best_score)
    return best
