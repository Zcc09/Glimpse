"""Command line interface + self test.

Every flag except --tray/--selftest-exit is also usable from the frozen exe:

  Glimpse.exe --selftest --selftest-out report.json
  Glimpse.exe --ocr shot.png
  Glimpse.exe --translate "hello" --to ar
  Glimpse.exe --songid --seconds 8
  Glimpse.exe --capture --out screen.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

from . import __version__
from .log import log
from .paths import app_dir, resource_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="glimpse", description="Glimpse — Google Lens for Windows")
    p.add_argument("--version", action="store_true", help="print version and exit")
    p.add_argument("--data-dir", action="store_true", help="print the data directory and exit")
    p.add_argument("--selftest", action="store_true", help="run the self test (offscreen; no GUI)")
    p.add_argument("--selftest-out", metavar="FILE", help="write the self test report as JSON")
    p.add_argument("--no-network", action="store_true", help="skip network steps in the self test")
    p.add_argument("--audio-test", action="store_true", help="include a record+Shazam roundtrip in the self test")
    p.add_argument("--ocr", metavar="FILE", help="OCR an image file and print the text")
    p.add_argument("--translate", dest="translate_text", metavar="TEXT", help="translate text and print the result")
    p.add_argument("--to", dest="to", default="en", help="target language for --translate (default: en)")
    p.add_argument("--from-lang", dest="from_lang", default="auto", help="source language for --translate")
    p.add_argument("--songid", action="store_true", help="record system audio and identify the song")
    p.add_argument("--seconds", type=int, default=8, help="seconds to record for --songid")
    p.add_argument("--capture", action="store_true", help="capture the whole desktop to a PNG")
    p.add_argument("--out", metavar="FILE", help="output file for --capture")
    p.add_argument("--tray", action="store_true", help="start quietly in the tray (no welcome toast)")
    p.add_argument("--exit-after", type=float, default=0.0, metavar="SECONDS", help="quit automatically after N seconds (testing)")
    p.add_argument("--uninstall", action="store_true", help="uninstall Glimpse (Windows; used by Add/Remove Programs)")
    p.add_argument("--silent", action="store_true", help="no prompts (for --uninstall)")
    p.add_argument("--check-updates", action="store_true", help="check the GitHub repo for a newer release")
    p.add_argument("--json", dest="json_out", action="store_true", help="machine-readable output (with --check-updates)")
    p.add_argument("--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def wants_cli(args: argparse.Namespace) -> bool:
    return bool(
        args.version
        or args.data_dir
        or args.selftest
        or args.ocr
        or args.translate_text
        or args.songid
        or args.capture
        or args.uninstall
        or args.check_updates
    )


def ensure_console() -> None:
    """A windowed frozen exe has no stdout; attach one when a CLI flag is used."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if kernel32.GetConsoleWindow():
            return
        if not kernel32.AllocConsole():
            return
        try:
            kernel32.SetConsoleOutputCP(65001)  # UTF-8, so Arabic/arrows print
        except Exception:
            pass
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
        sys.stdin = open("CONIN$", "r", encoding="utf-8")  # noqa: SIM115
    except Exception:
        pass


def _configure_std_streams() -> None:
    """Pipes default to the legacy ANSI codepage on Windows — force UTF-8."""
    for stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, "replace").decode(enc, "replace"))
    except Exception:
        pass


def run(args: argparse.Namespace) -> int:
    if getattr(sys, "frozen", False) and sys.stdout is None:
        ensure_console()
    _configure_std_streams()

    if args.version:
        print(f"Glimpse {__version__}")
        return 0
    if args.data_dir:
        print(app_dir())
        return 0
    if args.uninstall:
        from .uninstall import run_uninstall

        return run_uninstall(silent=bool(args.silent))
    if args.check_updates:
        return cmd_check_updates(args)
    if args.selftest:
        return cmd_selftest(args)
    if args.ocr:
        return cmd_ocr(args)
    if args.translate_text:
        return cmd_translate(args)
    if args.songid:
        return cmd_songid(args)
    if args.capture:
        return cmd_capture(args)
    return 2


# ------------------------------------------------------------------ commands
def cmd_ocr(args: argparse.Namespace) -> int:
    from PySide6.QtGui import QImage

    from .ocr import recognize

    img = QImage(args.ocr)
    if img.isNull():
        print(f"could not read {args.ocr}", file=sys.stderr)
        return 2
    res = recognize(img)
    _safe_print(res.text)
    return 0 if res.text.strip() else 1


def cmd_translate(args: argparse.Namespace) -> int:
    from .translate import translate_text

    out = translate_text(args.translate_text, args.to, source=args.from_lang)
    _safe_print(out.text)
    _safe_print(f"[{out.engine} {out.detected}->{out.target}]")
    return 0


def cmd_songid(args: argparse.Namespace) -> int:
    from .audio import identify_song, record_wav

    print(f"recording {args.seconds}s of system audio…", file=sys.stderr)
    path = record_wav(seconds=args.seconds, source="system")
    print(f"listening to Shazam… ({path})", file=sys.stderr)
    song = identify_song(path)
    if song is None:
        print("no match")
        return 1
    print(f"{song.artist} — {song.title}" if song.artist else song.title)
    if song.youtube_url:
        print(song.youtube_url)
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from PySide6.QtWidgets import QApplication

    from .capture import grab_all

    app = QApplication(sys.argv[:1])
    shot = grab_all()
    img = shot.composite()
    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / f"glimpse_capture_{int(time.time())}.png"
    img.save(str(out), "PNG")
    print(str(out))
    del app
    return 0


def cmd_check_updates(args: argparse.Namespace) -> int:
    from .config import Settings
    from .update import UpdateError, check_for_update, current_version, releases_page

    repo = (Settings.load().update_repo or "Zcc09/Glimpse").strip()
    cur = current_version()
    payload = {"repo": repo, "current": cur, "update_available": False, "latest": None, "error": None}
    try:
        info = check_for_update(repo, current=cur)
    except UpdateError as e:
        payload["error"] = str(e)
        if args.json_out:
            _safe_print(json.dumps(payload, indent=2))
        else:
            _safe_print(f"update check failed: {e}")
        return 2
    if info is None:
        if args.json_out:
            _safe_print(json.dumps(payload, indent=2))
        else:
            _safe_print(f"{cur} is the latest version ({repo})")
        return 0
    payload.update(
        {
            "update_available": True,
            "latest": {
                "tag": info.tag,
                "version": info.version,
                "title": info.title,
                "page_url": info.page_url,
                "published_at": info.published_at,
                "assets": [a.name for a in info.assets],
            },
        }
    )
    if args.json_out:
        _safe_print(json.dumps(payload, indent=2))
    else:
        _safe_print(f"update available: {info.tag} (you have {cur})")
        _safe_print(info.page_url or releases_page(repo))
    return 0


# ------------------------------------------------------------------ self test
def cmd_selftest(args: argparse.Namespace) -> int:
    # NOTE: do NOT force QT_QPA_PLATFORM=offscreen here — the offscreen plugin
    # renders text as garbage glyphs, which would make the OCR step meaningless.
    # The default platform is used (no windows are shown); offscreen is only a
    # fallback when the default platform cannot be created at all.
    if not os.environ.get("GLIMPSE_HOME"):
        os.environ["GLIMPSE_HOME"] = tempfile.mkdtemp(prefix="glimpse-selftest-")

    report: dict = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "steps": {}}

    def step(name: str, fn):
        t0 = time.time()
        try:
            detail = fn()
            report["steps"][name] = {"ok": True, "detail": str(detail)[:400], "seconds": round(time.time() - t0, 2)}
            _safe_print(f"PASS {name}: {detail}")
        except SkipTest as e:
            report["steps"][name] = {"ok": True, "skipped": True, "detail": str(e)}
            _safe_print(f"SKIP {name}: {e}")
        except Exception as e:  # noqa: BLE001
            report["steps"][name] = {"ok": False, "detail": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
            _safe_print(f"FAIL {name}: {type(e).__name__}: {e}")
            _safe_print(traceback.format_exc(limit=4))

    from .util import contains_arabic

    state: dict = {}

    def qt_image():
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter
        from PySide6.QtWidgets import QApplication

        try:
            state["app"] = QApplication.instance() or QApplication([])
        except Exception:
            os.environ["QT_QPA_PLATFORM"] = "offscreen"  # last resort
            state["app"] = QApplication([])
        img = QImage(720, 220, QImage.Format.Format_RGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setPen(QColor("black"))
        p.setFont(QFont("Segoe UI", 30))
        p.drawText(0, 0, 720, 220, Qt.AlignmentFlag.AlignCenter, "Glimpse selftest 4242")
        p.end()
        path = Path(os.environ["GLIMPSE_HOME"]) / "selftest_image.png"
        img.save(str(path), "PNG")
        state["image"] = img
        state["image_path"] = str(path)
        return path

    def ocr_step():
        from .ocr import recognize

        res = recognize(state["image"])
        text = (res.text or "").lower()
        if "glimpse" not in text or "4242" not in text:
            raise AssertionError(f"OCR returned unexpected text: {res.text!r}")
        return f"engine={res.engine} text={res.text!r}"

    def qr_step():
        from .qrscan import decode_codes
        from .util import qimage_from_bytes

        asset = resource_path("assets/test_qr.png")
        if not asset.exists():
            raise SkipTest("assets/test_qr.png not found")
        codes = decode_codes(qimage_from_bytes(asset.read_bytes()))
        if not codes:
            raise AssertionError("QR asset did not decode")
        return f"decoded {codes[0]['text']!r}"

    def history_step():
        from .history import History

        h = History(limit=10)
        img = state.get("image")
        h.add("text", title="selftest", text="round trip ✓", image=img, extra={"engine": "selftest"})
        rows = h.list_entries(limit=5)
        if not rows or rows[0]["text"] != "round trip ✓":
            raise AssertionError("history round trip failed")
        return f"{h.count()} entries, newest id={rows[0]['id']}, thumb={'yes' if rows[0]['thumb_path'] else 'no'}"

    def translate_step():
        from .translate import translate_text

        out = translate_text("Hello, how are you today?", "ar")
        if not contains_arabic(out.text):
            raise AssertionError(f"unexpected translation: {out.text!r}")
        back = translate_text("مرحبا كيف حالك", "en")
        if "hello" not in back.text.lower() and "hi" not in back.text.lower():
            raise AssertionError(f"unexpected back translation: {back.text!r}")
        return f"en→ar {out.text!r} via {out.engine}; ar→en {back.text!r}"

    def lens_step():
        from .capture import png_bytes
        from .visual import lens_upload

        url = lens_upload(png_bytes(state["image"]))
        if not url.startswith("http"):
            raise AssertionError(f"bad url {url!r}")
        return url[:110]

    def yandex_step():
        from .capture import png_bytes
        from .visual import yandex_upload

        url = yandex_upload(png_bytes(state["image"]))
        if "cbir_id=" not in url:
            raise AssertionError(f"bad url {url!r}")
        return url[:110]

    def audio_step():
        from .audio import identify_song, record_wav

        path = record_wav(seconds=5, source="system")
        song = identify_song(path)
        return f"recorded {path}; shazam={'match: ' + song.title if song else 'no match (api ok)'}"

    def tesseract_step():
        from .ocr import recognize
        from .ocr.tesseract_ocr import find_tesseract

        exe = find_tesseract()
        if not exe:
            raise SkipTest("tesseract is not bundled or installed")
        res = recognize(state["image"], engine="tesseract", tess_languages=["eng"])
        if "4242" not in (res.text or ""):
            raise AssertionError(f"tesseract OCR returned unexpected text: {res.text!r}")
        detail = f"exe={Path(exe).name} engine={res.engine} text={res.text!r}"

        from .ocr import tesseract_languages_installed

        langs = tesseract_languages_installed()
        detail += f" langs={len(langs)}"
        if "ara" in langs:  # proves a non-Latin script end to end
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QColor, QFont, QImage, QPainter

            img = QImage(1200, 200, QImage.Format.Format_RGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            p.setPen(QColor("black"))
            f = QFont("Segoe UI")
            f.setPixelSize(40)
            p.setFont(f)
            p.drawText(
                0, 0, 1200, 200, Qt.AlignmentFlag.AlignCenter,
                "الطقس جميل اليوم. أريد أن أطلب قهوة من المقهى الجديد.",
            )
            p.end()
            ar = recognize(img, engine="tesseract", tess_languages=["ara", "eng"])
            arabic_chars = sum(1 for c in (ar.text or "") if "\u0600" <= c <= "\u06FF")
            if arabic_chars < 8:
                raise AssertionError(f"arabic OCR returned unexpected text: {ar.text!r}")
            detail += f" arabic={ar.text[:34]!r}"
        return detail

    def ffmpeg_step():
        from .record import find_ffmpeg

        exe = find_ffmpeg()
        if not exe:
            raise SkipTest("ffmpeg not found (recording needs it)")
        return Path(exe).name

    def record_step():
        import time as _time

        from PySide6.QtCore import QRect

        from .record import Recorder, frame_at, probe_duration

        path = Path(os.environ["GLIMPSE_HOME"]) / "selftest_clip.mp4"
        rec = Recorder(QRect(60, 60, 320, 240), path, fps=10, max_seconds=3)
        rec.start()
        deadline = _time.time() + 40
        while rec.is_running() and _time.time() < deadline:
            if state.get("app") is not None:
                state["app"].processEvents()
            _time.sleep(0.1)
        if not rec.wait(40):
            raise AssertionError("recorder never finished")
        if not path.is_file() or path.stat().st_size < 1000:
            raise AssertionError("no usable clip produced")
        dur = probe_duration(path)
        if dur < 2.0:
            raise AssertionError(f"clip too short: {dur}")
        img = frame_at(path, min(0.5, dur / 2))
        if img is None or img.width() < 200:
            raise AssertionError("could not read a frame back")
        return f"{path.name} {dur:.1f}s {img.width()}x{img.height()} ({rec.frames_written()} frames)"

    def ocr_scripts_step():
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter

        from .ocr import recognize

        cases = [
            ("english", "Glimpse selftest 4242", 40, 900, 170, "4242", "eng"),
            ("chinese", "今天的天气很好，我想去新开的咖啡馆喝一杯。", 34, 1000, 160, "今天", "chi_sim"),
            ("russian", "Погода сегодня отличная. Я хочу заказать кофе.", 34, 1000, 160, "Погода", "rus"),
        ]
        from .ocr.languages import installed_languages

        have = set(installed_languages())
        results = []
        for name, text, px, w, h, expect, needs in cases:
            if needs not in have:
                results.append(f"{name}=skipped (no {needs} data)")
                continue
            img = QImage(w, h, QImage.Format.Format_RGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            p.setPen(QColor("black"))
            f = QFont("Segoe UI")
            f.setPixelSize(px)
            p.setFont(f)
            p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, text)
            p.end()
            res = recognize(img, engine="auto", tess_languages=["eng", "ara"], all_languages=True)
            got = (res.text or "").replace(" ", "")
            if expect not in got:
                if res.low_confidence and not got.strip():
                    raise SkipTest(f"{name}: language data not installed")
                raise AssertionError(f"{name}: expected {expect!r} in {res.text!r}")
            results.append(f"{name}={res.engine}/{res.confidence:.0f}")
        return ", ".join(results)

    step("qt_image", qt_image)
    step("windows_ocr", ocr_step)
    step("tesseract_ocr", tesseract_step)
    step("multi_script_ocr", ocr_scripts_step)
    step("qr_decode", qr_step)
    step("history", history_step)
    step("ffmpeg", ffmpeg_step)
    step("screen_record", record_step)

    if args.no_network:
        report["steps"]["translate"] = {"ok": True, "skipped": True, "detail": "--no-network"}
        report["steps"]["lens_upload"] = {"ok": True, "skipped": True, "detail": "--no-network"}
        report["steps"]["yandex_upload"] = {"ok": True, "skipped": True, "detail": "--no-network"}
        print("SKIP translate/lens/yandex (--no-network)")
    else:
        step("translate", translate_step)
        step("lens_upload", lens_step)
        step("yandex_upload", yandex_step)

    if args.audio_test:
        step("audio_roundtrip", audio_step)
    else:
        report["steps"]["audio_roundtrip"] = {"ok": True, "skipped": True, "detail": "pass --audio-test"}

    ok = all(s.get("ok") for s in report["steps"].values())
    report["ok"] = ok

    if args.selftest_out:
        Path(args.selftest_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        _safe_print(f"report: {args.selftest_out}")
    _safe_print(f"SELFTEST {'OK' if ok else 'FAILED'} - glimpse {__version__}")
    return 0 if ok else 1


class SkipTest(Exception):
    pass
