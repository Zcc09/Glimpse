"""Capability probe for Glimpse — run each risky tech on THIS machine, print PASS/FAIL.

Usage: .venv/Scripts/python.exe scripts/probe_env.py
"""
import asyncio
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import traceback
import wave

TMP = tempfile.gettempdir()


def p(*a):
    print(*a, flush=True)


def safe(name, fn):
    try:
        val = fn()
        p(f"PASS {name}: {val}")
        return True, val
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        p(f"FAIL {name}: {type(e).__name__}: {e}")
        p("    " + tb.replace("\n", "\n    "))
        return False, e


# ---------------------------------------------------------------- test image
def make_test_image():
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    app = QApplication.instance() or QApplication([])
    img = QImage(700, 220, QImage.Format_RGB32)
    img.fill(QColor("#ffffff"))
    pnt = QPainter(img)
    pnt.setPen(QColor("#101010"))
    pnt.setFont(QFont("Segoe UI", 28))
    pnt.drawText(0, 0, 700, 220, Qt.AlignmentFlag.AlignCenter, "Hello Glimpse 12345")
    pnt.end()
    path = os.path.join(TMP, "glimpse_probe.png")
    img.save(path)
    return path


# ---------------------------------------------------------------- windows OCR
async def _win_ocr(png: bytes):
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
    dec = await BitmapDecoder.create_async(stream)
    bmp = await dec.get_software_bitmap_async()
    eng = OcrEngine.try_create_from_user_profile_languages()
    src = "user_profile"
    if eng is None:
        eng = OcrEngine.try_create_from_language(Language("en-US"))
        src = "en-US"
    if eng is None:
        langs = [l.language_tag for l in OcrEngine.available_recognizer_languages]
        raise RuntimeError(f"no OCR engine available; recognizer langs={langs}")
    res = await eng.recognize_async(bmp)
    tag = eng.recognizer_language.language_tag if eng.recognizer_language else "?"
    return src, tag, " ".join(l.text for l in res.lines)


def probe_ocr(png_path):
    with open(png_path, "rb") as f:
        png = f.read()
    return asyncio.run(_win_ocr(png))


def probe_ocr_langs():
    from winsdk.windows.media.ocr import OcrEngine

    return [l.language_tag for l in OcrEngine.available_recognizer_languages]


# ---------------------------------------------------------------- screen grab
def probe_screen_grab():
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    scr = QGuiApplication.primaryScreen()
    geo = scr.geometry()
    vg = QGuiApplication.primaryScreen().virtualGeometry()
    pm = scr.grabWindow(0)
    if pm.isNull():
        raise RuntimeError("grabWindow returned null pixmap")
    return f"screen={geo.width()}x{geo.height()} dpr={scr.devicePixelRatio()} virtual={vg.width()}x{vg.height()} grabbed={pm.width()}x{pm.height()}"


# ---------------------------------------------------------------- translate
def probe_translate():
    from deep_translator import GoogleTranslator

    ar = GoogleTranslator(source="auto", target="ar").translate("Hello, how are you today?")
    en = GoogleTranslator(source="ar", target="en").translate("مرحبا كيف حالك")
    return f"en->ar={ar!r} ar->en={en!r}"


# ---------------------------------------------------------------- lens upload
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def probe_lens(png_path):
    import requests

    url = f"https://lens.google.com/v3/upload?stcs={int(time.time() * 1000)}&hl=en"
    with open(png_path, "rb") as f:
        files = {"encoded_image": ("image.png", f, "image/png")}
        r = requests.post(url, files=files, headers={"User-Agent": UA}, timeout=40, allow_redirects=False)
    loc = r.headers.get("Location")
    if r.status_code in (301, 302, 303, 307) and loc:
        return f"status={r.status_code} loc={loc[:120]}"
    # some versions answer 200 with html; look for a redirect url inside
    if r.status_code == 200:
        import re

        m = re.search(r'https://lens\.google\.com/[^\s"\']+', r.text)
        if m:
            return f"status=200 embedded={m.group(0)[:120]}"
    raise RuntimeError(f"unexpected status={r.status_code} body[:200]={r.text[:200]!r}")


def probe_yandex(png_path):
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    params = {
        "rpt": "imageview",
        "format": "json",
        "request": json.dumps({"blocks": [{"block": "b-page_type_search-by-image__link"}]}),
    }
    with open(png_path, "rb") as f:
        files = {"upfile": ("blob", f, "image/png")}
        r = s.post("https://yandex.com/images/search", params=params, files=files, timeout=40)
    j = r.json()
    cbir = j["blocks"][0]["params"]["url"]
    return f"cbir_url={cbir[:120]}"


# ---------------------------------------------------------------- QR
def probe_qr():
    import numpy as np
    import qrcode
    from PIL import Image
    import zxingcpp

    path = os.path.join(TMP, "glimpse_probe_qr.png")
    qrcode.make("https://example.com/glimpse-test").save(path)
    img = np.array(Image.open(path).convert("L"))
    results = zxingcpp.read_barcodes(img)
    if not results:
        raise RuntimeError("no barcode found in generated QR")
    return f"format={results[0].format} text={results[0].text!r}"


# ---------------------------------------------------------------- tone wav
def make_tone_wav(path, seconds=8.0, freq=440.0, rate=44100):
    n = int(rate * seconds)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        buf = bytearray()
        for i in range(n):
            val = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            buf += struct.pack("<h", val)
        w.writeframes(bytes(buf))
    return path


def probe_loopback(seconds=2.5):
    import audioop

    import pyaudiowpatch as pyaudio

    tone_path = make_tone_wav(os.path.join(TMP, "glimpse_probe_tone.wav"), seconds)
    pa = pyaudio.PyAudio()
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        spk = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        loop = None
        if spk.get("isLoopbackDevice"):
            loop = spk
        else:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("isLoopbackDevice") and spk["name"] in info["name"]:
                    loop = info
                    break
        if loop is None:
            raise RuntimeError("no WASAPI loopback device found")
        rate = int(loop["defaultSampleRate"])
        ch = int(loop["maxInputChannels"]) or 2
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=ch,
            rate=rate,
            input=True,
            input_device_index=loop["index"],
            frames_per_buffer=1024,
        )
        import winsound

        winsound.PlaySound(tone_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        frames = []
        for _ in range(int(rate / 1024 * seconds)):
            frames.append(stream.read(1024, exception_on_overflow=False))
        stream.stop_stream()
        stream.close()
        rms = audioop.rms(b"".join(frames), 2)
        # also write the captured wav for the test suite
        out = os.path.join(TMP, "glimpse_probe_loopback.wav")
        with wave.open(out, "w") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(frames))
        return f"loopback='{loop['name']}' rate={rate} ch={ch} rms={rms} wav={out}"
    finally:
        pa.terminate()


# ---------------------------------------------------------------- shazamio
def probe_shazam():
    from shazamio import Shazam

    wav = make_tone_wav(os.path.join(TMP, "glimpse_probe_shazam.wav"), 8.0)
    sh = Shazam()
    t0 = time.time()
    try:
        res = asyncio.run(sh.recognize(wav))
        took = time.time() - t0
        keys = list(res.keys()) if isinstance(res, dict) else type(res).__name__
        matches = res.get("matches", []) if isinstance(res, dict) else []
        return f"api_roundtrip_ok({took:.1f}s) keys={keys} n_matches={len(matches)}"
    except Exception as e:
        took = time.time() - t0
        return f"api_roundtrip_ok-but-exception({took:.1f}s) {type(e).__name__}: {str(e)[:160]}"


def main():
    p("== python ==", sys.version)
    ok_img, png = safe("qt_test_image", make_test_image)
    safe("qt_platform", lambda: __import__("PySide6").__version__)
    safe("screen_grab", probe_screen_grab)
    safe("ocr_languages", probe_ocr_langs)
    if ok_img:
        safe("windows_ocr", lambda: probe_ocr(png))
        safe("google_lens_upload", lambda: probe_lens(png))
        safe("yandex_upload", lambda: probe_yandex(png))
    safe("translate", probe_translate)
    safe("qr_decode", probe_qr)
    safe("audio_loopback", probe_loopback)
    safe("shazam_api", probe_shazam)
    p("== done ==")


if __name__ == "__main__":
    main()
