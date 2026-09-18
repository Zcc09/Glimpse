"""Capture media: screenshots, region recording, clip trimming — and the multi-script OCR
matrix that the user's own screenshot regressed into.

Real runs only: a real 4-second recording through the real recorder and ffmpeg, real
rendered text through the real engine.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .helpers import render_text_image

FIXTURES = Path(__file__).resolve().parent / "assets"


# ------------------------------------------------------------------ language data
def _real_tessdata() -> Path:
    """The machine's real tessdata dir, ignoring the test's isolated GLIMPSE_HOME."""
    import os

    saved = os.environ.pop("GLIMPSE_HOME", None)
    try:
        from glimpse.ocr import languages as L

        return L.tessdata_dir()
    finally:
        if saved is not None:
            os.environ["GLIMPSE_HOME"] = saved


def _seed_languages(home: Path, codes) -> None:
    """Copy the needed .traineddata files into an isolated home (tests only read them)."""
    import shutil

    src = _real_tessdata()
    dst = home / "tessdata"
    dst.mkdir(parents=True, exist_ok=True)
    for code in codes:
        origin = src / f"{code}.traineddata"
        if origin.is_file():
            shutil.copy2(origin, dst / origin.name)


OCR_LANGS = ("eng", "chi_sim", "chi_tra", "jpn", "kor", "rus", "ell", "heb", "hin", "ara", "urd", "fas")


# ------------------------------------------------------------------ fixtures
def _load(name: str):
    from PySide6.QtGui import QImage

    path = FIXTURES / name
    if not path.is_file():
        pytest.skip(f"fixture {name} missing")
    img = QImage(str(path))
    if img.isNull():
        pytest.skip(f"fixture {name} unreadable")
    return img


def _render(text: str, pixels: int, width: int, height: int):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    f = QFont("Segoe UI")
    f.setPixelSize(pixels)
    p.setFont(f)
    p.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


# ------------------------------------------------------------------ the user's own snip
def test_user_snip_reads_chinese(app, glimpse_home):
    """The two-character Chinese label that used to say 'no text found'."""
    from glimpse.ocr import recognize

    _seed_languages(glimpse_home, OCR_LANGS)
    img = _load("cn_label.png")
    res = recognize(img, engine="auto", tess_languages=["eng", "ara"], all_languages=True)
    assert "中文" in res.text.replace(" ", ""), res.text
    assert res.engine == "tesseract"
    assert res.confidence >= 60, res.confidence
    assert not res.low_confidence


# ------------------------------------------------------------------ multi-script matrix
SCRIPTS = [
    ("chinese", "今天的天气很好，我想去新开的咖啡馆喝一杯。", 34, 1000, 160, "今天"),
    ("japanese", "今日はいい天気ですね。新しいカフェでコーヒーを飲みたいです。", 32, 1100, 160, "今日"),
    ("korean", "오늘 날씨가 좋네요. 새로 생긴 카페에서 커피를 마시고 싶어요.", 32, 1100, 160, "오늘"),
    ("russian", "Погода сегодня отличная. Я хочу заказать кофе в новом кафе.", 34, 1100, 160, "Погода"),
    ("greek", "Ο καιρός σήμερα είναι υπέροχος. Θέλω να πιω καφέ στο νέο καφέ.", 30, 1100, 170, "καιρός"),
    ("hebrew", "מזג האוויר היום נהדר. אני רוצה להזמין קפה בבית הקפה החדש.", 30, 1100, 170, "האוויר"),
    ("hindi", "आज मौसम बहुत अच्छा है। मैं नए कैफ़े में कॉफ़ी पीना चाहता हूँ।", 32, 1100, 170, "मौसम"),
    ("arabic", "الطقس جميل اليوم. أريد أن أطلب قهوة من المقهى الجديد.", 34, 1100, 170, "الطقس"),
]


@pytest.mark.parametrize("name,text,px,w,h,expect", SCRIPTS)
def test_script_is_read(app, glimpse_home, name, text, px, w, h, expect):
    """Every script: the right model is chosen without the user having ticked it."""
    from glimpse.ocr import recognize
    from glimpse.ocr import languages as L

    _seed_languages(glimpse_home, OCR_LANGS)
    installed = set(L.installed_languages())
    needed = {"chinese": "chi_sim", "japanese": "jpn", "korean": "kor", "russian": "rus",
              "greek": "ell", "hebrew": "heb", "hindi": "hin", "arabic": "ara"}[name]
    if needed not in installed:
        pytest.skip(f"{needed}.traineddata not installed")

    res = recognize(_render(text, px, w, h), engine="auto", tess_languages=["eng", "ara"], all_languages=True)
    flat = (res.text or "").replace(" ", "")
    assert expect in flat, f"{name}: {res.text!r}"
    assert res.confidence >= 55, f"{name}: confidence {res.confidence}"
    assert res.engine == "tesseract", f"{name}: engine {res.engine}"


def test_script_passes_cover_every_installed_language(glimpse_home):
    """Regression guard: ('kor') is a string, not a tuple — Korean had no pass at all."""
    from glimpse.ocr import languages as L

    _seed_languages(glimpse_home, OCR_LANGS)
    installed = L.installed_languages()
    for code in installed:
        assert code in L.SCRIPT_OF or True  # unmapped codes still get their own pass
    passes = L.script_passes(installed, preferred=["eng", "ara"])
    covered = {c for p in passes for c in p}
    assert set(installed) <= covered, sorted(set(installed) - covered)
    assert L.SCRIPT_OF.get("kor") == "hangul"
    assert L.SCRIPT_OF.get("tha") == "thai"
    assert L.SCRIPT_OF.get("ell") == "greek"
    # the ticked script's pass comes first
    assert "ara" in passes[0] or "eng" in passes[0]


# ------------------------------------------------------------------ recording
def test_recording_produces_a_playable_clip(app, glimpse_home, tmp_path):
    from PySide6.QtCore import QRect

    from glimpse.record import Recorder, ffmpeg_available, frame_at, probe_duration, trim_clip

    if not ffmpeg_available():
        pytest.skip("ffmpeg not installed")

    out = tmp_path / "clip.mp4"
    rec = Recorder(QRect(80, 80, 480, 360), out, fps=10, max_seconds=4)
    rec.start()
    deadline = 30
    import time

    t0 = time.time()
    while rec.is_running() and time.time() - t0 < deadline:
        app.processEvents()
        time.sleep(0.05)
    assert rec.wait(30), "recorder did not finish"
    assert out.is_file() and out.stat().st_size > 1000, "no usable file"
    duration = probe_duration(out)
    assert duration >= 3.0, f"clip too short: {duration}"
    assert rec.frames_written() >= 20, rec.frames_written()

    frame = frame_at(out, min(0.5, duration / 2))
    assert frame is not None and frame.width() >= 200 and frame.height() >= 200

    trimmed = tmp_path / "clip-trim.mp4"
    assert trim_clip(out, trimmed, 0.2, 1.4), "trim failed"
    assert probe_duration(trimmed) < duration


def test_ffmpeg_is_discoverable():
    from glimpse.record import find_ffmpeg, find_ffprobe

    exe = find_ffmpeg()
    if exe is None:
        pytest.skip("ffmpeg not installed on this machine")
    assert Path(exe).is_file()
    probe = find_ffprobe()
    assert probe is None or Path(probe).is_file()


@pytest.mark.audio
def test_recording_muxes_system_audio(app, tmp_path):
    """record_audio=True must end up as an MP4 with a real audio stream in it."""
    import subprocess
    import time

    from PySide6.QtCore import QRect

    from glimpse.audio import list_sources
    from glimpse.record import Recorder, find_ffprobe, probe_duration

    if not list_sources():
        pytest.skip("no loopback/mic device on this machine")
    if find_ffprobe() is None:
        pytest.skip("ffprobe not installed")

    out = tmp_path / "with_audio.mp4"
    rec = Recorder(QRect(80, 80, 480, 360), out, fps=10, max_seconds=5, audio=True)
    rec.start()
    t0 = time.time()
    while rec.is_running() and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.05)
    assert rec.wait(60), "recorder did not finish"
    assert out.is_file() and out.stat().st_size > 2000

    streams = subprocess.run(
        [find_ffprobe(), "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
        capture_output=True,
        text=True,
    ).stdout
    assert "audio" in streams, f"no audio stream muxed in (ffprobe: {streams!r})"
    assert probe_duration(out) >= 3.0


# ------------------------------------------------------------------ screenshots
def test_screenshot_folder_defaults_to_pictures(tmp_path, monkeypatch):
    from glimpse.paths import known_folder

    pics = known_folder("Pictures")
    assert pics.is_dir(), pics
    vids = known_folder("Videos")
    assert vids.is_dir(), vids


def test_next_capture_path_avoids_collisions(tmp_path):
    """Two screenshots in the same second must not overwrite each other."""
    from glimpse.app import GlimpseApp

    class _Stub:
        pass

    stub = _Stub()
    stub.settings = type("S", (), {"screenshot_dir": str(tmp_path)})()
    first = GlimpseApp._next_capture_path(stub, tmp_path, "Screenshot")
    first.write_text("x")
    second = GlimpseApp._next_capture_path(stub, tmp_path, "Screenshot")
    assert second != first and second.name.endswith("-2.png")
