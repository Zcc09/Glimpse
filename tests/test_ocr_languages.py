"""OCR engine chain: scoring, dark-mode rescue, bundled Tesseract, multi-script data.

Real runs throughout: images are rendered on the real platform and pushed through the
same code the app uses.
"""
from __future__ import annotations

import pytest

from .helpers import render_text_image

ARABIC_SENTENCE = "الطقس جميل اليوم. أريد أن أطلب قهوة من المقهى الجديد."


def arabic_chars(text: str) -> int:
    return sum(1 for c in (text or "") if "\u0600" <= c <= "\u06FF")


def render_dark(text: str, width: int = 760, height: int = 240, pixels: int = 34):
    """Light text on a dark background — what a dark-mode UI snip looks like."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("#101418"))
    p = QPainter(img)
    p.setPen(QColor("#f2f6f9"))
    f = QFont("Segoe UI")
    f.setPixelSize(pixels)
    p.setFont(f)
    p.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


def render_arabic_sentence():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    img = QImage(1200, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    f = QFont("Segoe UI")
    f.setPixelSize(40)
    p.setFont(f)
    p.drawText(0, 0, 1200, 200, Qt.AlignmentFlag.AlignCenter, ARABIC_SENTENCE)
    p.end()
    return img


# ------------------------------------------------------------------ scoring
def test_score_separates_text_from_gibberish():
    from glimpse.ocr import MIN_PLAUSIBLE, is_plausible, score_text

    assert score_text("Glimpse selftest 4242") >= MIN_PLAUSIBLE
    assert score_text(ARABIC_SENTENCE) > score_text("Glimpse selftest 4242")
    # real outputs from wrong-language runs
    for garbage in ("un-.l-o.-l.i 14>+0", "I-Oyo", "J.æo-.\n89-43", "I_Y-J-L-O.-I-C", "ös.e.ö"):
        assert not is_plausible(garbage), garbage
    assert is_plausible("مرحبا")  # short but clean
    assert is_plausible("Hello world 1234")
    assert not is_plausible("")
    assert not is_plausible("   ")


def test_empty_result_scores_zero():
    from glimpse.ocr import score_text

    assert score_text("") == 0.0
    assert score_text(None) == 0.0


# ------------------------------------------------------------------ variants / dark mode
def test_dark_crops_get_an_inverted_variant(app):
    from glimpse.ocr import _mean_luma, prepare_variants

    img = render_dark("Glimpse 8899")
    assert _mean_luma(img) < 110
    variants = prepare_variants(img)
    assert len(variants) == 4
    assert _mean_luma(variants[0]) > 110  # inverted first: engines want dark text on light


def test_light_crops_are_not_inverted(app):
    from glimpse.ocr import _mean_luma, prepare_variants

    img = render_text_image("Glimpse 8899")
    assert _mean_luma(img) > 110
    variants = prepare_variants(img)
    assert _mean_luma(variants[0]) > 110


def test_windows_ocr_reads_dark_mode_text(app):
    from glimpse.ocr import recognize

    res = recognize(render_dark("Glimpse dark mode 8899"), engine="windows")
    assert "8899" in (res.text or ""), res.text


# ------------------------------------------------------------------ tesseract
def test_bundled_tesseract_reads_english(app, glimpse_home):
    from glimpse.ocr import recognize, tesseract_available

    if not tesseract_available():
        pytest.skip("no bundled tesseract in this checkout")
    res = recognize(
        render_text_image("Glimpse tesseract 5150"), engine="tesseract", tess_languages=["eng"]
    )
    assert "5150" in res.text, res.text
    assert res.engine == "tesseract"


def test_tesseract_survives_missing_language_data(app, glimpse_home):
    """A ticked-but-not-downloaded language must degrade, not explode."""
    from glimpse.ocr import recognize

    res = recognize(
        render_text_image("Glimpse fallback 6161"), engine="tesseract", tess_languages=["eng", "xyz"]
    )
    assert "6161" in res.text, res.text


def test_language_catalog_is_complete():
    from glimpse.ocr import languages as L

    assert len(L.LANGUAGE_NAMES) == 126, len(L.LANGUAGE_NAMES)
    assert {"eng", "ara", "rus", "chi_sim", "chi_tra", "jpn", "kor", "hin", "urd", "fas"} <= set(
        L.LANGUAGE_NAMES
    )
    assert set(L.COMMON) <= set(L.LANGUAGE_NAMES)
    assert "eng" in L.BUNDLED and "ara" in L.COMMON


# ------------------------------------------------------------------ network
@pytest.mark.network
def test_language_download_and_arabic_ocr(app, glimpse_home):
    """The whole point of this feature: download a script, then read it offline."""
    from glimpse.ocr import recognize
    from glimpse.ocr import languages as L

    L.ensure_bundled()
    if "ara" not in L.installed_languages():
        path = L.download_language("ara")
        assert path.stat().st_size > 100_000, path
    assert "ara" in L.installed_languages()

    img = render_arabic_sentence()
    res = recognize(img, engine="tesseract", tess_languages=["ara", "eng"])
    assert arabic_chars(res.text) >= 8, res.text
    assert not res.low_confidence, res.text

    # and the auto chain must pick tesseract over the English-only Windows engine
    auto = recognize(img, engine="auto", tess_languages=["ara", "eng"])
    assert auto.engine == "tesseract", auto.engine
    assert arabic_chars(auto.text) >= 8, auto.text
