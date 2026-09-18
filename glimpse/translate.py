"""Translation with a fallback chain and chunking.

Order (configurable): clients5 dict-chrome-ex → MyMemory → deep-translator Google.
Google's consumer endpoints rate-limit some networks; the chain keeps working.
Each engine retries once, because the free endpoints throttle in short bursts.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from .log import log

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CHUNK_LIMIT = 1200


class TranslationError(RuntimeError):
    pass


@dataclass
class TranslationOut:
    text: str
    detected: str
    engine: str
    target: str
    chunks: list[str] = field(default_factory=list)


_session: Optional[requests.Session] = None


def _sess() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": UA})
    return _session


# ------------------------------------------------------------------ chunking
def chunk_text(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    cur = ""
    for para in re.split(r"(?<=\n)", text):
        if len(cur) + len(para) <= limit:
            cur += para
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        while len(para) > limit:
            cut = para.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(para[:cut])
            para = para[cut:]
        cur = para
    if cur:
        chunks.append(cur)
    return chunks


# ------------------------------------------------------------------ engines
def _google_clients5(chunk: str, source: str, target: str) -> tuple[str, str]:
    r = _sess().get(
        "https://clients5.google.com/translate_a/t",
        params={"client": "dict-chrome-ex", "sl": source or "auto", "tl": target, "q": chunk},
        timeout=15,
    )
    r.raise_for_status()
    j = r.json()
    if isinstance(j, list) and j and isinstance(j[0], list) and j[0] and isinstance(j[0][0], str):
        detected = j[0][1] if len(j[0]) > 1 and isinstance(j[0][1], str) else (source or "auto")
        return j[0][0], detected
    raise TranslationError("unexpected response shape")


def _mymemory(chunk: str, source: str, target: str) -> tuple[str, str]:
    src = source if source and source != "auto" else "auto"
    pair = f"{src}|{target}"
    r = _sess().get(
        "https://api.mymemory.translated.net/get",
        params={"q": chunk, "langpair": pair},
        timeout=15,
    )
    r.raise_for_status()
    j = r.json()
    data = j.get("responseData") or {}
    text = data.get("translatedText")
    if not text:
        raise TranslationError(f"mymemory: {j.get('responseDetails') or 'no text'}")
    detected = j.get("matches", [{}])[0].get("source", src) if isinstance(j.get("matches"), list) else src
    if detected and "|" in str(detected):
        detected = str(detected).split("|")[0]
    return text, detected or src


def _google_web(chunk: str, source: str, target: str) -> tuple[str, str]:
    from deep_translator import GoogleTranslator

    out = GoogleTranslator(source=source or "auto", target=target).translate(chunk)
    if not out:
        raise TranslationError("empty translation")
    return out, source or "auto"


ENGINES: dict[str, Callable[[str, str, str], tuple[str, str]]] = {
    "google": _google_clients5,
    "mymemory": _mymemory,
    "google-web": _google_web,
}


def _run_engine(fn, chunk: str, source: str, target: str, attempts: int = 2, delay: float = 0.6):
    """Call one engine, retrying once — the free endpoints throttle briefly."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn(chunk, source, target)
        except Exception as e:  # noqa: BLE001
            last = e
            if i + 1 < attempts:
                time.sleep(delay)
    raise last if last else TranslationError("engine failed")


def translate_text(
    text: str,
    target: str,
    source: str = "auto",
    prefer: str = "auto",
) -> TranslationOut:
    """Translate `text` into `target`, trying engines until one works."""
    text = text or ""
    if not text.strip():
        return TranslationOut(text="", detected=source, engine="none", target=target)
    if target in ("", "auto"):
        raise TranslationError("no target language")

    order = ["google", "mymemory", "google-web"]
    if prefer in ENGINES:
        order.remove(prefer)
        order.insert(0, prefer)

    last: Exception | None = None
    for name in order:
        fn = ENGINES[name]
        try:
            parts: list[str] = []
            detected = source
            for ch in chunk_text(text):
                out, det = _run_engine(fn, ch, source, target)
                parts.append(out)
                if det and det != "auto":
                    detected = det
            joined = "".join(parts)
            if joined.strip():
                return TranslationOut(text=joined, detected=detected, engine=name, target=target, chunks=parts)
            raise TranslationError("empty result")
        except Exception as e:  # noqa: BLE001
            last = e
            log.info("translate engine %s failed: %s: %s", name, type(e).__name__, e)
            continue
    raise TranslationError(f"all translation engines failed ({type(last).__name__}: {last})")
