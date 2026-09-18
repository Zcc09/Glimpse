"""Settings (JSON) + hotkey parsing. All values are plain data so tests can round-trip them."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

from .log import log
from .paths import settings_path

# ------------------------------------------------------------------ languages
LANGUAGES: dict[str, str] = {
    "auto": "Auto-detect",
    "en": "English",
    "ar": "العربية Arabic",
    "fr": "Français French",
    "es": "Español Spanish",
    "de": "Deutsch German",
    "it": "Italiano Italian",
    "pt": "Português Portuguese",
    "ru": "Русский Russian",
    "hi": "हिन्दी Hindi",
    "ur": "اردو Urdu",
    "fa": "فارسی Persian",
    "tr": "Türkçe Turkish",
    "he": "עברית Hebrew",
    "zh-CN": "中文 Chinese (Simplified)",
    "zh-TW": "中文 Chinese (Traditional)",
    "ja": "日本語 Japanese",
    "ko": "한국어 Korean",
    "id": "Bahasa Indonesia",
    "ms": "Bahasa Melayu",
    "th": "ไทย Thai",
    "vi": "Tiếng Việt Vietnamese",
    "nl": "Nederlands Dutch",
    "pl": "Polski Polish",
    "sv": "Svenska Swedish",
    "uk": "Українська Ukrainian",
    "el": "Ελληνικά Greek",
    "ro": "Română Romanian",
    "bn": "বাংলা Bengali",
    "tl": "Filipino",
    "ta": "தமிழ் Tamil",
    "te": "తెలుగు Telugu",
    "mr": "मराठी Marathi",
    "gu": "ગુજરાતી Gujarati",
    "pa": "ਪੰਜਾਬੀ Punjabi",
    "sw": "Kiswahili Swahili",
    "am": "አማርኛ Amharic",
    "ku": "Kurdî Kurdish",
    "az": "Azərbaycan Azerbaijani",
    "cs": "Čeština Czech",
    "da": "Dansk Danish",
    "fi": "Suomi Finnish",
    "no": "Norsk Norwegian",
    "hu": "Magyar Hungarian",
    "sk": "Slovenčina Slovak",
    "bg": "Български Bulgarian",
    "sr": "Српски Serbian",
    "hr": "Hrvatski Croatian",
    "ne": "नेपाली Nepali",
    "si": "සිංහල Sinhala",
    "km": "ខ្មែរ Khmer",
    "my": "မြန်မာ Burmese",
    "af": "Afrikaans",
}

# ------------------------------------------------------------------ hotkeys
_MODS = {
    "ctrl": 0x0002,
    "control": 0x0002,
    "alt": 0x0001,
    "shift": 0x0004,
    "win": 0x0008,
    "super": 0x0008,
    "meta": 0x0008,
}
_VK_NAMES = {
    "space": 0x20,
    "print": 0x2C,
    "printscreen": 0x2C,
    "prtsc": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "backspace": 0x08,
    "esc": 0x1B,
    "escape": 0x1B,
    "comma": 0xBC,
    "period": 0xBE,
    "dot": 0xBE,
    "slash": 0xBF,
    "semicolon": 0xBA,
    "quote": 0xDE,
    "minus": 0xBD,
    "equal": 0xBB,
    "plus": 0xBB,
    "grave": 0xC0,
    "backtick": 0xC0,
    "bracketleft": 0xDB,
    "bracketright": 0xDD,
    "backslash": 0xDC,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}


def parse_hotkey(spec: str) -> Optional[tuple[int, int]]:
    """'Ctrl+Alt+L' → (mods, vk). None when unparseable."""
    if not spec or not isinstance(spec, str):
        return None
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", spec.strip()) if p.strip()]
    if not parts:
        return None
    mods = 0
    key = None
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
            continue
        if key is not None:
            return None
        if len(p) == 1 and (p.isalpha() or p.isdigit()):
            key = ord(p.upper())
        elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", p):
            key = 0x70 + int(p[1:]) - 1
        elif p in _VK_NAMES:
            key = _VK_NAMES[p]
        else:
            return None
    if key is None:
        return None
    # single letter/digit without a modifier would block normal typing
    if mods == 0 and (0x30 <= key <= 0x5A):
        return None
    return mods, key


def format_hotkey(spec: str) -> str:
    return spec


# ------------------------------------------------------------------ settings
@dataclass
class Settings:
    # behaviour
    default_action: str = "text"          # text | translate | visual | qr | copy
    target_lang: str = "auto"             # 'auto' = swap between secondary_lang and en
    secondary_lang: str = "ar"            # the "other" language for auto-swap
    # engines
    ocr_engine: str = "windows"           # windows | tesseract
    ocr_language: str = ""                # '' = choose automatically
    visual_engine: str = "google"         # google | yandex
    translate_engine: str = "auto"        # auto | google | mymemory
    # capture
    copy_image_on_capture: bool = True
    save_history: bool = True
    history_limit: int = 500
    # audio
    audio_source: str = "system"          # system | mic
    mic_device_name: str = ""
    record_seconds: int = 8
    # app
    hotkeys: dict = field(
        default_factory=lambda: {
            "capture": "Ctrl+Alt+L",
            "translate": "Ctrl+Alt+T",
            "visual": "Ctrl+Alt+S",
            "songid": "Ctrl+Alt+M",
        }
    )
    autostart: bool = False
    show_toasts: bool = True
    first_run_done: bool = False

    # -------------------------------------------------------------- io
    @classmethod
    def load(cls, path: Path | str | None = None) -> "Settings":
        p = Path(path) if path else settings_path()
        s = cls()
        try:
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                known = {f.name for f in fields(cls)}
                for k, v in raw.items():
                    if k in known:
                        setattr(s, k, v)
                # hotkeys merge (so a new action keeps its default)
                hk = raw.get("hotkeys")
                if isinstance(hk, dict):
                    merged = cls().hotkeys
                    merged.update({k: v for k, v in hk.items() if isinstance(v, str)})
                    s.hotkeys = merged
        except Exception as e:
            log.warning("settings load failed (%s); using defaults", e)
        return s

    def save(self, path: Path | str | None = None) -> None:
        p = Path(path) if path else settings_path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def to_dict(self) -> dict:
        return asdict(self)

    # -------------------------------------------------------------- helpers
    def resolved_target(self, text: str) -> str:
        """Which language to translate INTO, given the source text."""
        from .util import contains_arabic

        if self.target_lang and self.target_lang != "auto":
            return self.target_lang
        other = self.secondary_lang or "ar"
        return "en" if contains_arabic(text) else other
