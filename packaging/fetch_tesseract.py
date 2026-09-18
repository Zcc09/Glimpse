"""Assemble a minimal, redistributable Tesseract bundle in vendor/tesseract/.

Source: conda-forge's win-64 `tesseract` package (Apache-2.0), fetched with
micromamba. We keep tesseract.exe + the DLLs it actually needs + eng/osd language
data; every other language is downloaded on demand in the app (tessdata_fast).

Run once per build machine:  .venv/Scripts/python.exe packaging/fetch_tesseract.py
It is idempotent: an existing vendor/tesseract with a working tesseract.exe is kept.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "tesseract"
ENV = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "tessenv"
TESSDATA_FAST_RAW = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{code}.traineddata"

# Never ship these: they are the OS/loader shims and the UCRT copy that the
# conda build links against explicitly (removing them stops the exe from starting).
KEEP_ALWAYS_PREFIXES = ("api-ms-win-",)
KEEP_ALWAYS = {"ucrtbase.dll", "tesseract.exe", "tesseract55.dll", "leptonica-1.87.0.dll"}
# Everything else is tried for removal, one at a time, verified by a real OCR run.
PRUNE_CANDIDATES = [
    "libcurl.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll", "krb5_64.dll",
    "libxml2.dll", "archive.dll", "nghttp2.dll", "libssh2.dll",
    "brotlidec.dll", "brotlicommon.dll", "utf8proc.dll", "libdeflate.dll",
    "icudt78.dll", "icuin78.dll", "icuuc78.dll", "icuin.dll", "icuuc.dll", "icutu.dll", "icutu78.dll",
    "iconv.dll", "zstd.dll", "libzstd.dll", "jpeg8.dll", "libjpeg.dll", "libopenjp2.dll",
    "libtiff.dll", "libwebp.dll", "libwebpmux.dll", "libwebpdemux.dll", "giflib.dll",
    "lzma.dll", "liblzma.dll", "z.dll", "zlib.dll", "libpng16.dll", "libpng.dll",
    "charset-1.dll", "double-conversion.dll", "libgcc_s_seh-1.dll", "libstdc++-6.dll",
    "winpthread-1.dll", "libwinpthread-1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def stage_from_conda() -> int:
    """Copy the conda env's tesseract into vendor/tesseract."""
    bin_dir = ENV / "Library" / "bin"
    exe = bin_dir / "tesseract.exe"
    if not exe.is_file():
        log(f"missing {exe} — create the env first:\n"
            f"  micromamba create -y -p \"{ENV}\" -c conda-forge tesseract")
        return 2
    VENDOR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, VENDOR / "tesseract.exe")
    copied_dlls = 0
    for dll in sorted(bin_dir.glob("*.dll")):
        shutil.copy2(dll, VENDOR / dll.name)
        copied_dlls += 1
    tessdata = VENDOR / "tessdata"
    tessdata.mkdir(exist_ok=True)
    for code in ("eng", "osd"):
        src = ENV / "share" / "tessdata" / f"{code}.traineddata"
        if src.is_file():
            shutil.copy2(src, tessdata / f"{code}.traineddata")
    log(f"staged tesseract.exe + {copied_dlls} DLLs + eng/osd language data")
    return 0


def render_samples(tmp: Path) -> tuple[Path, Path]:
    """Two images: Latin and Arabic text (the Arabic one proves the language path)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    def render(path: Path, text: str, font: str, size: int, width: int, height: int) -> None:
        img = QImage(width, height, QImage.Format.Format_RGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setPen(QColor("black"))
        f = QFont(font)
        f.setPixelSize(size)
        p.setFont(f)
        p.drawText(0, 0, width, height, Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        img.save(str(path), "PNG")

    en = tmp / "sample_en.png"
    ar = tmp / "sample_ar.png"
    render(en, "Glimpse tesseract bundle 1234", "Segoe UI", 56, 900, 220)
    # a full sentence: Tesseract's Arabic model is unreliable on very short phrases,
    # so the bundle check uses text it reads well (and that a snipped line would contain)
    render(ar, ARABIC_SENTENCE, "Segoe UI", 40, 1200, 200)
    return en, ar


ARABIC_SENTENCE = "الطقس جميل اليوم. أريد أن أطلب قهوة من المقهى الجديد."


def ocr(exe: Path, image: Path, langs: str, tessdata: Path, cwd: Path) -> tuple[int, str]:
    r = subprocess.run(
        [str(exe), str(image), "stdout", "-l", langs, "--tessdata-dir", str(tessdata), "--psm", "6"],
        capture_output=True, cwd=str(cwd), timeout=120,
    )
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def tesseract_works(workdir: Path, tessdata: Path) -> bool:
    """English *and* Arabic must both read correctly — pruning must not break either."""
    exe = workdir / "tesseract.exe"
    tmp = Path(tempfile.mkdtemp(prefix="glimpse-tess-check-"))
    try:
        en, ar = render_samples(tmp)
        rc, text = ocr(exe, en, "eng", tessdata, workdir)
        if rc != 0 or "1234" not in text:
            return False
        if not (tessdata / "ara.traineddata").is_file():
            return True  # Arabic not staged here; the caller checks that separately
        rc, text = ocr(exe, ar, "ara", tessdata, workdir)
        return rc == 0 and sum(1 for c in text if "\u0600" <= c <= "\u06FF") >= 8
    except Exception as e:  # noqa: BLE001
        log(f"   check failed: {type(e).__name__}: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prune_strays() -> list[str]:
    """Drop anything in vendor/tesseract that is not engine/runtime material.

    Scratch files (test images, captured output) must never reach a release build;
    the spec has a whitelist too, this keeps the staging folder itself honest.
    """
    allowed = (".exe", ".dll", ".traineddata", ".md", ".txt")
    removed = []
    for path in VENDOR.rglob("*"):
        if path.is_file() and not path.name.lower().endswith(allowed):
            removed.append(str(path.relative_to(VENDOR)))
            path.unlink()
    return removed


def main() -> int:
    strays = prune_strays()
    if strays:
        log(f"removed {len(strays)} stray file(s) from vendor/tesseract: {strays[:6]}")
    if (VENDOR / "tesseract.exe").is_file():
        log(f"vendor/tesseract already present ({sum(f.stat().st_size for f in VENDOR.glob('*') if f.is_file())/1e6:.0f} MB of files)")
    else:
        rc = stage_from_conda()
        if rc:
            return rc

    tessdata = VENDOR / "tessdata"
    if not tesseract_works(VENDOR, tessdata):
        log("FAIL: the staged tesseract does not OCR correctly")
        return 1
    log("baseline works")

    # prune DLLs that are demonstrably not needed
    pruned = []
    for name in PRUNE_CANDIDATES:
        target = VENDOR / name
        if not target.is_file() or name in KEEP_ALWAYS or name.startswith(KEEP_ALWAYS_PREFIXES):
            continue
        backup = target.with_suffix(target.suffix + ".keep")
        target.rename(backup)
        if tesseract_works(VENDOR, tessdata):
            backup.unlink()
            pruned.append(name)
            log(f"pruned {name}")
        else:
            backup.rename(target)
            log(f"kept {name} (required)")

    total = sum(f.stat().st_size for f in VENDOR.rglob("*") if f.is_file())
    log(f"\nvendor/tesseract: {total/1e6:.1f} MB in {len(list(VENDOR.rglob('*')))} entries; pruned {len(pruned)} DLLs")

    # Arabic must work once its data file is present
    tmp = Path(tempfile.mkdtemp(prefix="glimpse-tess-ar-"))
    ar_ok = False
    try:
        _en, ar_img = render_samples(tmp)
        ara = tessdata / "ara.traineddata"
        if not ara.is_file():
            log("fetching ara.traineddata to prove the language path…")
            import requests
            r = requests.get(TESSDATA_FAST_RAW.format(code="ara"), timeout=120,
                             headers={"User-Agent": "Glimpse-build"})
            r.raise_for_status()
            ara.write_bytes(r.content)
        rc, text = ocr(VENDOR / "tesseract.exe", ar_img, "ara", tessdata, VENDOR)
        log(f"arabic OCR rc={rc}: {text!r}")
        ar_ok = rc == 0 and any("\u0600" <= c <= "\u06FF" for c in text)
        log("arabic path OK" if ar_ok else "ARABIC PATH FAILED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    write_notice()
    return 0 if ar_ok else 1


def write_notice() -> None:
    (VENDOR / "NOTICE.md").write_text(
        "# Bundled Tesseract OCR\n\n"
        "This folder contains the Tesseract OCR engine (Apache License 2.0,\n"
        "https://github.com/tesseract-ocr/tesseract) as built by conda-forge, plus its\n"
        "runtime DLLs and the `eng`/`osd` language data from tessdata_fast.\n\n"
        "Language data: https://github.com/tesseract-ocr/tessdata_fast (Apache-2.0).\n"
        "Glimpse downloads further languages on demand into %APPDATA%/Glimpse/tessdata.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
