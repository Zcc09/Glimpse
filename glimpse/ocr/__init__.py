"""OCR engines: Windows.Media.Ocr (default, no extra installs) + Tesseract fallback."""
from __future__ import annotations

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


class OcrError(RuntimeError):
    pass


def _prepare_png(image: QImage, upscale_to: int = 1000, max_dim: int = 2500) -> bytes:
    """Upscale small crops (helps OCR), clamp huge ones, encode PNG."""
    from PySide6.QtCore import Qt

    from ..util import png_bytes

    img = image
    if img.format() != QImage.Format.Format_ARGB32:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    longest = max(w, h)
    if longest < upscale_to and longest > 0:
        factor = min(3.0, upscale_to / longest)
        w, h = max(1, round(w * factor)), max(1, round(h * factor))
        img = img.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    longest = max(img.width(), img.height())
    if longest > max_dim:
        factor = max_dim / longest
        img = img.scaled(
            max(1, round(img.width() * factor)),
            max(1, round(img.height() * factor)),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return png_bytes(img)


def recognize(image: QImage, language: str = "", engine: str = "") -> OcrResult:
    """Dispatch to the configured engine, falling back to the other one."""
    engine = (engine or "windows").lower()
    if engine == "tesseract":
        from .tesseract_ocr import TesseractOcr, find_tesseract

        if find_tesseract():
            return TesseractOcr().recognize(image, language)
        log.warning("tesseract not found on PATH; using Windows OCR")
        engine = "windows"

    if engine == "windows":
        try:
            from .windows_ocr import recognize_windows

            return recognize_windows(image, language)
        except Exception as e:  # noqa: BLE001
            log.warning("Windows OCR failed (%s); trying tesseract", e)
            from .tesseract_ocr import TesseractOcr, find_tesseract

            if find_tesseract():
                return TesseractOcr().recognize(image, language)
            raise OcrError(
                "Windows OCR is unavailable and Tesseract is not installed. "
                "Install a Windows language pack (Settings → Time & language → "
                "Language & region → Add a language, with 'Optical character recognition') "
                "or install Tesseract from UB-Mannheim."
            ) from e
    raise OcrError(f"unknown OCR engine: {engine}")


def available_languages() -> list[str]:
    try:
        from .windows_ocr import available_languages as langs

        return langs()
    except Exception:
        return []
