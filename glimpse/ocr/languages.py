"""Tesseract language data: the full tessdata_fast list plus download helpers.

Language files are downloaded on demand from tessdata_fast (Apache-2.0, ~1-4 MB each)
into %APPDATA%/Glimpse/tessdata, so only the languages you actually use cost disk space.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Optional

import requests

from ..log import log
from ..paths import app_dir, resource_path

TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{code}.traineddata"
BUNDLED = ("eng", "osd")

# code -> display name (tessdata_fast, 126 languages; names are best-effort)
LANGUAGE_NAMES: dict[str, str] = {
    "afr": "Afrikaans",
    "amh": "Amharic",
    "ara": "Arabic",
    "asm": "Assamese",
    "aze": "Azerbaijani",
    "aze_cyrl": "Azerbaijani (Cyrillic)",
    "bel": "Belarusian",
    "ben": "Bengali",
    "bod": "Tibetan",
    "bos": "Bosnian",
    "bre": "Breton",
    "bul": "Bulgarian",
    "cat": "Catalan",
    "ceb": "Cebuano",
    "ces": "Czech",
    "chi_sim": "Chinese (Simplified)",
    "chi_sim_vert": "Chinese (Simplified, vertical)",
    "chi_tra": "Chinese (Traditional)",
    "chi_tra_vert": "Chinese (Traditional, vertical)",
    "chr": "Cherokee",
    "cos": "Corsican",
    "cym": "Welsh",
    "dan": "Danish",
    "deu": "German",
    "deu_latf": "deu_latf",
    "div": "Dhivehi",
    "dzo": "Dzongkha",
    "ell": "Greek",
    "eng": "English",
    "enm": "Middle English",
    "epo": "Esperanto",
    "equ": "equ",
    "est": "Estonian",
    "eus": "Basque",
    "fao": "Faroese",
    "fas": "Persian",
    "fil": "Filipino",
    "fin": "Finnish",
    "fra": "French",
    "frk": "Frankish",
    "frm": "Middle French",
    "fry": "Western Frisian",
    "gla": "Scottish Gaelic",
    "gle": "Irish",
    "glg": "Galician",
    "grc": "Ancient Greek",
    "guj": "Gujarati",
    "hat": "Haitian Creole",
    "heb": "Hebrew",
    "hin": "Hindi",
    "hrv": "Croatian",
    "hun": "Hungarian",
    "hye": "Armenian",
    "iku": "Inuktitut",
    "ind": "Indonesian",
    "isl": "Icelandic",
    "ita": "Italian",
    "ita_old": "Italian (Old)",
    "jav": "Javanese",
    "jpn": "Japanese",
    "jpn_vert": "Japanese (vertical)",
    "kan": "Kannada",
    "kat": "Georgian",
    "kat_old": "Georgian (Old)",
    "kaz": "Kazakh",
    "khm": "Khmer",
    "kir": "Kyrgyz",
    "kmr": "Kurdish (Northern)",
    "kor": "Korean",
    "kor_vert": "Korean (vertical)",
    "lao": "Lao",
    "lat": "Latin",
    "lav": "Latvian",
    "lit": "Lithuanian",
    "ltz": "Luxembourgish",
    "mal": "Malayalam",
    "mar": "Marathi",
    "mkd": "Macedonian",
    "mlt": "Maltese",
    "mon": "Mongolian",
    "mri": "Māori",
    "msa": "Malay",
    "mya": "Burmese",
    "nep": "Nepali",
    "nld": "Dutch",
    "nor": "Norwegian",
    "oci": "Occitan",
    "ori": "Odia",
    "osd": "osd",
    "pan": "Punjabi",
    "pol": "Polish",
    "por": "Portuguese",
    "pus": "Pashto",
    "que": "Quechua",
    "ron": "Romanian",
    "rus": "Russian",
    "san": "Sanskrit",
    "sin": "Sinhala",
    "slk": "Slovak",
    "slv": "Slovenian",
    "snd": "Sindhi",
    "spa": "Spanish",
    "spa_old": "Spanish (Old)",
    "sqi": "Albanian",
    "srp": "Serbian",
    "srp_latn": "Serbian (Latin)",
    "sun": "Sundanese",
    "swa": "Swahili",
    "swe": "Swedish",
    "syr": "Syriac",
    "tam": "Tamil",
    "tat": "Tatar",
    "tel": "Telugu",
    "tgk": "Tajik",
    "tha": "Thai",
    "tir": "Tigrinya",
    "ton": "Tongan",
    "tur": "Turkish",
    "uig": "Uyghur",
    "ukr": "Ukrainian",
    "urd": "Urdu",
    "uzb": "Uzbek",
    "uzb_cyrl": "Uzbek (Cyrillic)",
    "vie": "Vietnamese",
    "yid": "Yiddish",
    "yor": "Yoruba",
}

SORTED_LANGUAGES = sorted(LANGUAGE_NAMES.items(), key=lambda kv: (kv[1].lower(), kv[0]))




# languages offered up-front in the UI (the rest are searchable)
COMMON = [
    "eng", "ara", "fra", "deu", "spa", "ita", "por", "rus", "ukr", "tur", "fas", "urd", "hin", "ben",
    "heb", "ell", "nld", "pol", "swe", "ron", "ces", "chi_sim", "chi_tra", "jpn", "kor", "vie", "tha",
    "ind", "msa", "fil", "tam", "tel",
]


def tessdata_dir() -> Path:
    """Where language files live (%APPDATA%/Glimpse/tessdata)."""
    d = app_dir() / "tessdata"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_tessdata_dir():
    """Languages shipped inside the build (frozen: tesseract/, dev: vendor/tesseract/)."""
    for rel in ("tesseract/tessdata", "vendor/tesseract/tessdata"):
        try:
            p = resource_path(rel)
            if p.is_dir():
                return p
        except Exception:
            pass
    return None


def installed_languages() -> list[str]:
    """Languages ready to use: bundled ones (copied in on demand) plus downloads."""
    ensure_bundled()
    return sorted(p.stem for p in tessdata_dir().glob("*.traineddata"))


def ensure_bundled() -> None:
    """Copy the bundled language files into the user's tessdata dir once."""
    dst = tessdata_dir()
    src = bundled_tessdata_dir()
    if not src:
        return
    for code in BUNDLED:
        target = dst / f"{code}.traineddata"
        if target.exists():
            continue
        origin = src / f"{code}.traineddata"
        if origin.exists():
            try:
                shutil.copy2(origin, target)
            except OSError as e:  # noqa: BLE001
                log.warning("could not copy %s: %s", origin, e)


def download_language(code: str, progress=None, timeout: int = 180) -> Path:
    """Fetch one language file from tessdata_fast; returns the local path."""
    if code not in LANGUAGE_NAMES:
        raise ValueError(f"unknown tesseract language: {code}")
    dest = tessdata_dir() / f"{code}.traineddata"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    url = TESSDATA_URL.format(code=code)
    tmp = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Glimpse"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    os.replace(tmp, dest)
    log.info("downloaded tessdata %s (%d bytes)", code, dest.stat().st_size)
    return dest


def label(code: str) -> str:
    return f"{LANGUAGE_NAMES.get(code, code)} ({code})"
