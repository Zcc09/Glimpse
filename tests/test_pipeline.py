"""Pipeline tests: every backend exercised for real (network / audio where needed)."""
from __future__ import annotations

import json
import os
import time

import pytest

from .helpers import has_loopback, make_qr_image, render_text_image, tone_wav


# ------------------------------------------------------------------ OCR
def test_windows_ocr_reads_rendered_text(app):
    from glimpse.ocr import recognize

    img = render_text_image("Glimpse pipeline 777")
    res = recognize(img)
    text = (res.text or "").lower()
    assert "glimpse" in text, f"OCR missed the text: {res.text!r}"
    assert "777" in text, f"OCR missed the number: {res.text!r}"
    assert res.engine == "windows"
    assert res.lines, "no line boxes returned"


def test_ocr_survives_tiny_crops(app):
    """Small selections are upscaled before OCR."""
    from glimpse.ocr import recognize

    img = render_text_image("ABCDEF 123", width=260, height=70, pointsize=16)
    res = recognize(img)
    assert "123" in (res.text or ""), f"OCR failed on tiny crop: {res.text!r}"


# ------------------------------------------------------------------ QR
def test_qr_decode(app):
    from glimpse.qrscan import decode_codes

    payload = "https://example.com/glimpse-qr-test"
    codes = decode_codes(make_qr_image(payload))
    assert codes, "no code decoded"
    assert codes[0]["text"] == payload


# ------------------------------------------------------------------ capture crop math
def test_crop_math_single_and_multi_screen(app):
    """crop() must map logical selections onto device pixels through the screen DPR."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPixmap

    from glimpse.capture import Piece, ScreenShot

    dev1 = QImage(200, 100, QImage.Format.Format_RGB32)
    dev1.fill(QColor("red"))
    dev2 = QImage(300, 100, QImage.Format.Format_RGB32)
    dev2.fill(QColor("blue"))

    p1 = Piece(rect=QRect(0, 0, 100, 50), dpr=2.0, pixmap=QPixmap.fromImage(dev1))
    p2 = Piece(rect=QRect(100, 0, 300, 100), dpr=1.0, pixmap=QPixmap.fromImage(dev2))
    shot = ScreenShot(virtual_rect=QRect(0, 0, 400, 100), pieces=[p1, p2])

    single = shot.crop(QRect(10, 10, 40, 20))
    assert single.width() == 80 and single.height() == 40, (single.width(), single.height())
    assert single.pixelColor(5, 5).red() > 200

    # spans both screens: normalised to the highest DPR (2.0)
    multi = shot.crop(QRect(50, 10, 200, 30))
    assert multi.width() == 400, multi.width()
    assert multi.pixelColor(5, 5).red() > 200, "left part should come from screen 1"
    assert multi.pixelColor(300, 5).blue() > 200, "right part should come from screen 2"


def test_composite_size_matches_virtual_rect(app):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPixmap

    from glimpse.capture import Piece, ScreenShot

    dev = QImage(160, 90, QImage.Format.Format_RGB32)
    dev.fill(QColor("green"))
    piece = Piece(rect=QRect(-100, -50, 80, 45), dpr=2.0, pixmap=QPixmap.fromImage(dev))
    shot = ScreenShot(virtual_rect=QRect(-100, -50, 80, 45), pieces=[piece])
    img = shot.composite()
    assert img.width() == 80 and img.height() == 45


# ------------------------------------------------------------------ history
def test_history_roundtrip(glimpse_home, app):
    from glimpse.history import History

    h = History(limit=5)
    img = render_text_image("history test")
    eid = h.add("text", title="t", text="hello history", image=img, extra={"k": "v"})
    row = h.get(eid)
    assert row["text"] == "hello history"
    assert row["extra"]["k"] == "v"
    assert os.path.exists(row["image_path"])
    assert os.path.exists(row["thumb_path"])
    assert h.count() == 1

    for i in range(7):
        h.add("text", text=f"entry {i}")
    assert h.count() == 5, "limit not enforced"
    assert h.list_entries(limit=10)[0]["text"] == "entry 6"

    h.delete(eid)
    assert h.get(eid) is None


# ------------------------------------------------------------------ settings
def test_settings_roundtrip(glimpse_home):
    from glimpse.config import Settings, parse_hotkey

    s = Settings.load()
    assert s.hotkeys["capture"] == "Ctrl+Alt+L"
    s.target_lang = "fr"
    s.secondary_lang = "ar"
    s.record_seconds = 11
    s.save()
    back = Settings.load()
    assert back.target_lang == "fr" and back.record_seconds == 11
    assert json.loads((glimpse_home / "settings.json").read_text(encoding="utf-8"))["target_lang"] == "fr"

    assert parse_hotkey("Ctrl+Alt+L") == (0x0002 | 0x0001, 0x4C)
    assert parse_hotkey("ctrl+shift+F5") == (0x0002 | 0x0004, 0x74)
    assert parse_hotkey("Print") == (0, 0x2C)
    assert parse_hotkey("L") is None          # letter without modifiers
    assert parse_hotkey("Ctrl+Nonsense") is None
    assert Settings().resolved_target("hello") == "ar"
    assert Settings().resolved_target("مرحبا") == "en"


# ------------------------------------------------------------------ network
@pytest.mark.network
def test_translation_chain_real(glimpse_home):
    from glimpse import translate

    out = translate.translate_text("The weather is beautiful today, isn't it?", "ar")
    assert any("\u0600" <= c <= "\u06FF" for c in out.text), out.text
    assert out.engine in ("google", "mymemory", "google-web")

    back = translate.translate_text("أريد أن أطلب قهوة", "en")
    assert "coffee" in back.text.lower() or "order" in back.text.lower(), back.text


def test_translation_retries_transient_failures(monkeypatch):
    """One throttled response must not fail the whole translation."""
    from glimpse import translate

    calls = {"n": 0}

    def flaky(chunk, source, target):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTP 429 (transient)")
        return "مرحبا", "en"

    monkeypatch.setitem(translate.ENGINES, "google", flaky)
    out = translate.translate_text("hello there", "ar", prefer="google")
    assert out.text == "مرحبا"
    assert out.engine == "google"
    assert calls["n"] == 2, "engine should have been retried once"


def test_translation_falls_through_engines(monkeypatch):
    from glimpse import translate

    def broken(chunk, source, target):
        raise RuntimeError("down")

    def good(chunk, source, target):
        return "ahla", "en"

    monkeypatch.setitem(translate.ENGINES, "google", broken)
    monkeypatch.setitem(translate.ENGINES, "mymemory", good)
    out = translate.translate_text("hello", "ar")
    assert out.text == "ahla" and out.engine == "mymemory"


@pytest.mark.network
def test_long_text_is_chunked(glimpse_home):
    from glimpse.translate import chunk_text

    long = ("This is a sentence that repeats. " * 120).strip()
    chunks = chunk_text(long, limit=500)
    assert len(chunks) > 1
    assert "".join(chunks) == long
    assert all(len(c) <= 500 for c in chunks)


@pytest.mark.network
def test_visual_search_uploads(app, glimpse_home):
    from glimpse.capture import png_bytes
    from glimpse.visual import lens_upload, yandex_upload

    img = render_text_image("Glimpse visual search 2026")
    data = png_bytes(img)

    lens = lens_upload(data)
    assert lens.startswith("http") and "google" in lens

    yandex = yandex_upload(data)
    assert "cbir_id=" in yandex


# ------------------------------------------------------------------ audio
@pytest.mark.audio
def test_loopback_captures_playing_audio(app, glimpse_home):
    if not has_loopback():
        pytest.skip("no WASAPI loopback device")
    import array
    import math
    import wave

    import winsound

    from glimpse.audio import record_wav

    tone = tone_wav(str(glimpse_home / "tone.wav"), seconds=6.0)
    winsound.PlaySound(tone, winsound.SND_FILENAME | winsound.SND_ASYNC)
    path = record_wav(seconds=3, source="system")
    with wave.open(path) as w:
        frames = w.readframes(w.getnframes())
        samples = array.array("h")
        samples.frombytes(frames)
    rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))
    assert rms > 300, f"recorded audio is silent (rms={rms})"
    assert os.path.getsize(path) > 10000


@pytest.mark.audio
@pytest.mark.network
def test_shazam_roundtrip(app, glimpse_home):
    """A pure tone will not match, but the whole request path must work."""
    if not has_loopback():
        pytest.skip("no WASAPI loopback device")
    from glimpse.audio import identify_song, record_wav

    path = record_wav(seconds=4, source="system")
    song = identify_song(path)
    assert song is None or song.title, f"unexpected result: {song!r}"


def test_list_sources_lists_devices():
    from glimpse.audio import list_sources

    sources = list_sources()
    assert any(s["kind"] == "system" for s in sources), "no loopback source listed"
    assert all({"kind", "name", "index", "default"} <= set(s) for s in sources)


# ------------------------------------------------------------------ misc
def test_looks_like_math_and_arabic_helpers():
    from glimpse.util import contains_arabic, looks_like_math

    assert looks_like_math("3x + 12 = 45")
    assert looks_like_math("sqrt(144) / 2")
    assert not looks_like_math("Hello world 123")
    assert contains_arabic("مرحبا")
    assert not contains_arabic("hello")
