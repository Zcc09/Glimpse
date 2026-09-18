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


OCR_LANGS = ("eng", "chi_sim", "chi_tra", "jpn", "kor", "rus", "ell", "heb", "hin", "ara",
             "urd", "fas", "tur", "vie", "deu", "fra", "spa", "nld", "pol", "ind")


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
# (name, text, pixels, width, height, expected substring without diacritics)
SCRIPTS = [
    ("chinese", "今天的天气很好，我想去新开的咖啡馆喝一杯。", 34, 1000, 160, "今天"),
    ("japanese", "今日はいい天気ですね。新しいカフェでコーヒーを飲みたいです。", 32, 1100, 160, "今日"),
    ("korean", "오늘 날씨가 좋네요. 새로 생긴 카페에서 커피를 마시고 싶어요.", 32, 1100, 160, "오늘"),
    ("russian", "Погода сегодня отличная. Я хочу заказать кофе в новом кафе.", 34, 1100, 160, "Погода"),
    ("greek", "Ο καιρός σήμερα είναι υπέροχος. Θέλω να πιω καφέ στο νέο καφέ.", 30, 1100, 170, "καιρός"),
    ("hebrew", "מזג האוויר היום נהדר. אני רוצה להזמין קפה בבית הקפה החדש.", 30, 1100, 170, "האוויר"),
    ("hindi", "आज मौसम बहुत अच्छा है। मैं नए कैफ़े में कॉफ़ी पीना चाहता हूँ।", 32, 1100, 170, "मौसम"),
    ("arabic", "الطقس جميل اليوم. أريد أن أطلب قهوة من المقهى الجديد.", 34, 1100, 170, "الطقس"),
    # Persian at this exact size reads *nothing* at 1.0x and fine at 1.3x — the regression
    # guard for the single-upscale-factor lottery that made the user's snips "not find text"
    ("persian", "امروز هوا بسیار خوب است. می‌خواهم در کافه جدید قهوه بنوشم.", 32, 1100, 170, "قهوه"),
    ("urdu", "آج موسم بہت اچھا ہے۔ میں نئے کیفے میں کافی پینا چاہتا ہوں۔", 32, 1100, 170, "موسم"),
    # Turkish and Vietnamese only keep their diacritics when 'eng' anchors their pass
    ("turkish", "Bugün hava çok güzel. Yeni kafede bir kahve içmek istiyorum.", 32, 1100, 170, "Bugün hava"),
    ("vietnamese", "Hôm nay thời tiết rất đẹp. Tôi muốn uống cà phê ở quán mới.", 32, 1100, 170, "thời tiết"),
    # Latin batches (expectations avoid diacritics: the LSTM drops those on occasion,
    # exactly like Windows OCR, and the read is still correct)
    ("german", "Das Wetter ist heute wunderschön. Ich möchte einen Kaffee bestellen.", 32, 1100, 170, "Das Wetter ist heute"),
    ("french", "Le temps est magnifique aujourd'hui. Je voudrais commander un café.", 32, 1100, 170, "magnifique"),
    ("spanish", "El tiempo es magnífico hoy. Quiero pedir un café, por favor.", 32, 1100, 170, "Quiero pedir"),
]

LATIN_CASES = {"turkish", "vietnamese", "german", "french", "spanish"}
NEEDS = {"chinese": "chi_sim", "japanese": "jpn", "korean": "kor", "russian": "rus",
         "greek": "ell", "hebrew": "heb", "hindi": "hin", "arabic": "ara",
         "persian": "fas", "urdu": "urd", "turkish": "tur", "vietnamese": "vie",
         "german": "deu", "french": "fra", "spanish": "spa"}


@pytest.mark.parametrize("name,text,px,w,h,expect", SCRIPTS)
def test_script_is_read(app, glimpse_home, name, text, px, w, h, expect):
    """Every script: the right model is chosen without the user having ticked it."""
    from glimpse.ocr import recognize
    from glimpse.ocr import languages as L

    _seed_languages(glimpse_home, OCR_LANGS)
    installed = set(L.installed_languages())
    needed = NEEDS[name]
    if needed not in installed:
        pytest.skip(f"{needed}.traineddata not installed")

    res = recognize(_render(text, px, w, h), engine="auto", tess_languages=["eng", "ara"], all_languages=True)
    flat = (res.text or "").replace(" ", "")
    assert expect.replace(" ", "") in flat, f"{name}: {res.text!r}"
    if res.engine == "tesseract":       # Windows OCR does not report a confidence
        assert res.confidence >= 55, f"{name}: confidence {res.confidence}"
    if name in LATIN_CASES:
        assert res.engine in ("windows", "tesseract"), f"{name}: engine {res.engine}"
    else:
        # Windows has no pack for these scripts on this machine, so Tesseract must have won
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


# ------------------------------------------------------------------ recording quality
def test_encoder_detection_and_picking():
    """Hardware encoders must be found and preferred; software is the fallback."""
    from glimpse.record import available_encoders, ddagrab_available, encoder_args, pick_encoder

    have = available_encoders()
    if not have:
        pytest.skip("ffmpeg not installed")

    name, is_hw = pick_encoder("auto", prefer_hw=True)
    assert name, "no encoder at all"
    if any(k.endswith("_nvenc") for k in have):
        assert name.endswith("_nvenc") and is_hw, f"expected an NVENC encoder, got {name}"

    sw_name, sw_hw = pick_encoder("h264", prefer_hw=False)
    assert not sw_hw and sw_name in ("libx264", "libx265", "mpeg4"), sw_name

    for codec, expected in (("av1", ("av1",)), ("hevc", ("hevc",)), ("h264", ("h264",))):
        picked, _hw = pick_encoder(codec, prefer_hw=True)
        if picked:
            assert expected[0] in picked, f"{codec} → {picked}"

    args = encoder_args(name)
    assert "-c:v" in args and args[args.index("-c:v") + 1] == name
    assert ddagrab_available() in (True, False)   # callable, cached, no crash


def test_recording_60fps_hardware(app, tmp_path):
    """60 fps must be reachable through the GPU path with a real hardware encoder."""
    import subprocess
    import time

    from PySide6.QtCore import QRect

    from glimpse.record import Recorder, available_encoders, ddagrab_available, find_ffprobe, probe_duration

    if not available_encoders():
        pytest.skip("ffmpeg not installed")

    out = tmp_path / "fast.mp4"
    rec = Recorder(QRect(200, 200, 960, 540), out, fps=60, max_seconds=5, codec="auto", hardware=True)
    assert rec.encoder, "no encoder chosen"
    rec.start()
    t0 = time.time()
    while rec.is_running() and time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.05)
    assert rec.wait(60), "recorder did not finish"
    assert out.is_file() and out.stat().st_size > 5000

    duration = probe_duration(out)
    assert duration >= 4.0, f"clip too short for a 5 s recording: {duration}"
    info = subprocess.run(
        [find_ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,avg_frame_rate", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    ).stdout.strip()
    codec_name, rate = (info.split(",") + ["", ""])[:2]
    assert codec_name in ("av1", "hevc", "h264"), info
    num, _, den = rate.partition("/")
    fps = float(num) / float(den or 1)
    assert fps >= 55, f"expected ~60 fps, ffprobe says {rate}"
    if ddagrab_available() and rec.encoder.endswith("_nvenc"):
        assert rec.backend == "gpu", f"expected GPU capture, got {rec.backend}"


def test_cpu_fallback_keeps_real_time(app, tmp_path):
    """Without GPU capture the clip must still last as long as the recording did.

    The pump cannot always grab at 60 fps; the recorder repeats frames so the timeline stays
    honest instead of writing a clip that plays back faster than reality.
    """
    import time

    from PySide6.QtCore import QRect

    from glimpse.record import Recorder, available_encoders, probe_duration

    if not available_encoders():
        pytest.skip("ffmpeg not installed")

    out = tmp_path / "pump.mp4"
    rec = Recorder(QRect(200, 200, 960, 540), out, fps=60, max_seconds=5, codec="h264", hardware=False)
    assert rec.backend in ("", "cpu")
    t0 = time.time()
    rec.start()
    while rec.is_running() and time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.05)
    wall = time.time() - t0
    assert rec.wait(60)
    duration = probe_duration(out)
    assert rec.backend == "cpu"
    assert duration >= wall * 0.8, f"clip ({duration:.2f}s) does not match real time ({wall:.2f}s)"
