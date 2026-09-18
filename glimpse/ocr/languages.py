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

# ------------------------------------------------------------------ scripts
# Which writing system each language uses. Used to build one recognition pass per
# script, so a snip in Chinese is read by a Han model even when the user's ticked
# languages are English and Arabic (a Latin-only read of 中文 returns garbage).
SCRIPT_OF: dict[str, str] = {}
for _script, _codes in {
    "latin": (
        "eng", "fra", "deu", "spa", "ita", "por", "nld", "pol", "tur", "ind", "msa", "fil", "vie",
        "afr", "cat", "ces", "slk", "hun", "ron", "hrv", "bos", "slv", "est", "lav", "lit", "fin",
        "swe", "dan", "nor", "isl", "mlt", "cym", "gle", "glg", "eus", "sqi", "jav", "sun", "hat",
        "swa", "kur", "ltz", "frk", "tgl", "uzb", "aze", "tat", "epo", "lat",
    ),
    "han": ("chi_sim", "chi_tra", "jpn"),
    "hangul": ("kor",),
    "arabic": ("ara", "urd", "fas", "pus", "snd"),
    "cyrillic": ("rus", "ukr", "bel", "bul", "srp", "mkd", "kaz", "kir", "tgk", "mon", "uzb_cyrl"),
    "hebrew": ("heb", "yid"),
    "greek": ("ell", "grc"),
    "thai": ("tha",),
    "devanagari": ("hin", "mar", "nep", "san"),
    "bengali": ("ben", "asm"),
    "gurmukhi": ("pan",),
    "gujarati": ("guj",),
    "tamil": ("tam",),
    "telugu": ("tel",),
    "kannada": ("kan",),
    "malayalam": ("mal",),
    "sinhala": ("sin",),
    "khmer": ("khm",),
    "lao": ("lao",),
    "myanmar": ("mya",),
    "georgian": ("kat",),
    "armenian": ("hye",),
    "ethiopic": ("amh", "tir"),
}.items():
    # a bare string here would iterate its characters (the ("kor") trap) — normalise
    _codes = (_codes,) if isinstance(_codes, str) else _codes
    for _code in _codes:
        SCRIPT_OF[_code] = _script

# pass order for the all-languages search: the scripts a screen snip is most likely to
# contain come first, Latin last (the ticked languages are always tried before these)
SCRIPT_ORDER = (
    "han", "hangul", "arabic", "cyrillic", "devanagari", "hebrew", "greek", "thai",
    "bengali", "gurmukhi", "gujarati", "tamil", "telugu", "kannada", "malayalam", "sinhala",
    "khmer", "lao", "myanmar", "georgian", "armenian", "ethiopic", "latin",
)
# a pass is capped so loading a dozen models does not turn one snip into a coffee break
MAX_LANGS_PER_PASS = 6

# The languages worth trying first inside the big Latin family. Order matters more than
# it should: within one pass the early languages dominate the model mixture, and Turkish
# and Vietnamese only keep their diacritics when they follow English directly
# (eng+tur+vie+ind+nld+pol reads them at ~96, eng+nld+pol+tur+ind+vie at ~93 with 'gok'/'igmek').
_LATIN_PRIORITY = ("eng", "fra", "deu", "spa", "ita", "por", "tur", "vie", "ind", "nld", "pol")
# per-script ordering hints (the first ones are tried before the rarest)
SCRIPT_PRIORITY: dict[str, tuple] = {
    "latin": _LATIN_PRIORITY,
    "arabic": ("ara", "urd", "fas", "pus", "snd"),
    "cyrillic": ("rus", "ukr", "bel", "bul", "srp", "kaz", "mkd", "mon"),
    "han": ("chi_sim", "chi_tra", "jpn"),
    "devanagari": ("hin", "mar", "nep", "san"),
}


def script_passes(installed, preferred=(), limit: int = MAX_LANGS_PER_PASS) -> list[list[str]]:
    """Recognition passes: one per script over the installed languages, best guess first.

    Ticking a language does not narrow the search — it only decides which *script* is tried
    first, and which language inside that script is ranked before the others. One pass per
    script (all of its installed languages together) is what reads Urdu with an Arabic model
    installed, or Arabic when only Urdu was ticked: the LSTM has the vocabulary of every
    language it is given.

    A script with more languages than one pass can hold is split into batches in priority
    order — capping the Latin family at the first six left Turkish and Vietnamese to be read
    by an English model (about 7 confidence points and every diacritic lost).
    """
    have = set(installed)
    pref = [c for c in preferred if c in have]
    pref_scripts = {SCRIPT_OF.get(c, "other") for c in pref}
    passes: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def add(codes):
        key = tuple(sorted(codes))
        if codes and key not in seen:
            seen.add(key)
            passes.append(list(codes))

    def batch(codes):
        """Split one script's languages into passes of ``limit``.

        Every batch keeps the script's anchor language (English for Latin): the LSTM reads
        Turkish and Vietnamese at ~96 with `eng` in the pass and ~92 without it — the shared
        vocabulary is what makes the diacritics come out right.
        """
        if not codes:
            return
        script = SCRIPT_OF.get(codes[0], "")
        priority = SCRIPT_PRIORITY.get(script, ())
        anchor = next((c for c in priority if c in codes), codes[0])
        codes = sorted(
            codes,
            key=lambda c: (0 if c in pref else 1, priority.index(c) if c in priority else 99, c),
        )
        for i in range(0, len(codes), limit):
            chunk = codes[i : i + limit]
            if anchor not in chunk:
                chunk = [anchor] + chunk[: limit - 1]
            add(chunk)

    ordered = [s for s in SCRIPT_ORDER if s in pref_scripts]
    ordered += [s for s in SCRIPT_ORDER if s not in pref_scripts]
    for script in ordered:
        batch([c for c in have if SCRIPT_OF.get(c) == script])
    # anything without a script mapping still gets a pass of its own
    add([c for c in have if c not in SCRIPT_OF][:limit])
    return passes


def cjk_space_fix(text: str) -> str:
    """Tesseract spaces Han/Kana glyphs apart ('中 文'); join them back up.

    Hangul is deliberately excluded: Korean words are separated by spaces.
    """
    import re

    cjk = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    t = re.sub(rf"(?<=[{cjk}])\s+(?=[{cjk}])", "", text or "")
    t = re.sub(rf"(?<=[{cjk}])\s+(?=[，。！？、；：）】」』])", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def char_script(ch: str) -> str:
    """Which writing system a single character belongs to."""
    o = ord(ch)
    if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F:
        return "kana"
    if 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF:
        return "han"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
        return "hangul"
    if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
        return "arabic"
    if 0x0400 <= o <= 0x052F or 0x2DE0 <= o <= 0x2DFF:
        return "cyrillic"
    if 0x0590 <= o <= 0x05FF:
        return "hebrew"
    if 0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF:
        return "greek"
    for script, lo, hi in (
        ("thai", 0x0E00, 0x0E7F), ("lao", 0x0E80, 0x0EFF), ("tibetan", 0x0F00, 0x0FFF),
        ("myanmar", 0x1000, 0x109F), ("georgian", 0x10A0, 0x10FF), ("ethiopic", 0x1200, 0x137F),
        ("khmer", 0x1780, 0x17FF), ("devanagari", 0x0900, 0x097F), ("bengali", 0x0980, 0x09FF),
        ("gurmukhi", 0x0A00, 0x0A7F), ("gujarati", 0x0A80, 0x0AFF), ("tamil", 0x0B80, 0x0BFF),
        ("telugu", 0x0C00, 0x0C7F), ("kannada", 0x0C80, 0x0CFF), ("malayalam", 0x0D00, 0x0D7F),
        ("sinhala", 0x0D80, 0x0DFF), ("armenian", 0x0530, 0x058F),
    ):
        if lo <= o <= hi:
            return script
    if ch.isalpha():
        return "latin"
    return "other"


def pass_scripts(langs) -> set[str]:
    """The scripts a set of languages is expected to produce (Han also covers Kana)."""
    out = {SCRIPT_OF.get(c, "other") for c in langs}
    if "han" in out:
        out.add("kana")
    return out


def script_consistency(text: str, langs) -> float:
    """Fraction of letters in ``text`` that belong to the scripts of ``langs``.

    A Cyrillic model reading Greek text produces mostly Greek letters: high confidence,
    wrong script. This is what breaks the tie.
    """
    accepted = pass_scripts(langs)
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if char_script(c) in accepted) / len(letters)


def dominant_script(text: str) -> str:
    """The script most of the letters in ``text`` belong to ('' when there are none)."""
    from collections import Counter

    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return ""
    script, count = Counter(char_script(c) for c in letters).most_common(1)[0]
    return script if count > len(letters) / 2 else ""


# Windows OCR language tags → the script those packs can actually read
WINDOWS_TAG_SCRIPT = {
    "en": "latin", "fr": "latin", "de": "latin", "es": "latin", "it": "latin", "pt": "latin",
    "nl": "latin", "pl": "latin", "sv": "latin", "da": "latin", "nb": "latin", "nn": "latin",
    "fi": "latin", "tr": "latin", "id": "latin", "ms": "latin", "vi": "latin", "cs": "latin",
    "hu": "latin", "ro": "latin", "sk": "latin", "hr": "latin", "sl": "latin", "et": "latin",
    "lv": "latin", "lt": "latin", "ca": "latin", "gl": "latin", "af": "latin", "sq": "latin",
    "az": "latin", "eu": "latin", "fil": "latin", "sq": "latin", "cy": "latin", "ga": "latin",
    "ar": "arabic", "fa": "arabic", "ur": "arabic", "he": "hebrew", "ru": "cyrillic",
    "uk": "cyrillic", "bg": "cyrillic", "sr": "cyrillic", "kk": "cyrillic", "mk": "cyrillic",
    "be": "cyrillic", "el": "greek", "th": "thai", "hi": "devanagari", "mr": "devanagari",
    "ne": "devanagari", "bn": "bengali", "gu": "gujarati", "pa": "gurmukhi", "ta": "tamil",
    "te": "telugu", "kn": "kannada", "ml": "malayalam", "si": "sinhala", "km": "khmer",
    "lo": "lao", "my": "myanmar", "ka": "georgian", "hy": "armenian", "am": "ethiopic",
    "zh": "han", "ja": "han", "ko": "hangul",
}


def windows_scripts(tags) -> set[str]:
    """Scripts the installed Windows OCR packs can read (e.g. only 'latin' for en-GB)."""
    out: set[str] = set()
    for tag in tags or ():
        base = str(tag).split("-")[0].lower()
        script = WINDOWS_TAG_SCRIPT.get(base)
        if script:
            out.add(script)
            if script == "han":
                out.add("kana")
    return out



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
