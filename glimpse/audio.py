"""Audio identification: record system output (WASAPI loopback) or mic, then Shazam it."""
from __future__ import annotations

import asyncio
import os
import time
import wave
from dataclasses import dataclass, field
from typing import Callable, Optional

from .log import log
from .paths import app_dir

FRAMES_PER_BUFFER = 1024


class AudioError(RuntimeError):
    pass


class CaptureCancelled(AudioError):
    pass


@dataclass
class SongResult:
    title: str
    artist: str = ""
    cover_url: str = ""
    youtube_url: str = ""
    shazam_url: str = ""
    apple_url: str = ""
    genre: str = ""
    raw: dict = field(default_factory=dict)


# ------------------------------------------------------------------ devices
def list_sources() -> list[dict]:
    """[{'kind','name','index','default'}] for system loopback + microphones."""
    import pyaudiowpatch as pyaudio

    out: list[dict] = []
    pa = pyaudio.PyAudio()
    try:
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        except Exception:
            default_out = None
        for info in pa.get_loopback_device_info_generator():
            is_default = bool(default_out and default_out.get("name") in info.get("name", ""))
            out.append({"kind": "system", "name": info["name"], "index": int(info["index"]), "default": is_default})
        try:
            default_in = pa.get_default_input_device_info()
            default_in_name = default_in.get("name", "")
        except Exception:
            default_in_name = ""
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("isLoopbackDevice"):
                continue
            if int(info.get("maxInputChannels", 0)) < 1:
                continue
            out.append(
                {
                    "kind": "mic",
                    "name": info["name"],
                    "index": int(info["index"]),
                    "default": info.get("name") == default_in_name,
                }
            )
    finally:
        pa.terminate()
    return out


def _pick_device(pa, source: str, device_name: str):
    import pyaudiowpatch as pyaudio

    if source == "mic":
        if device_name:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if device_name.lower() in str(info.get("name", "")).lower() and not info.get("isLoopbackDevice"):
                    return info
        return pa.get_default_input_device_info()

    # system loopback
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    except Exception:
        default_out = None
    candidates = list(pa.get_loopback_device_info_generator())
    if device_name:
        for c in candidates:
            if device_name.lower() in str(c.get("name", "")).lower():
                return c
    if default_out:
        for c in candidates:
            if str(default_out.get("name", "")) in str(c.get("name", "")):
                return c
    if candidates:
        return candidates[0]
    raise AudioError("No WASAPI loopback device found — cannot capture system audio.")


# ------------------------------------------------------------------ recording
def record_wav(
    seconds: int = 8,
    source: str = "system",
    device_name: str = "",
    progress: Optional[Callable[[float], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """Record `seconds` of audio to a WAV file; returns the path."""
    import pyaudiowpatch as pyaudio

    seconds = max(3, min(30, int(seconds)))
    pa = pyaudio.PyAudio()
    frames: list[bytes] = []
    try:
        dev = _pick_device(pa, source, device_name)
        rate = int(dev.get("defaultSampleRate") or 48000)
        ch = int(dev.get("maxInputChannels") or 2)
        ch = 1 if ch < 1 else min(ch, 2)
        log.info("recording %ss from '%s' (rate=%s ch=%s)", seconds, dev.get("name"), rate, ch)
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=ch,
            rate=rate,
            input=True,
            input_device_index=int(dev["index"]),
            frames_per_buffer=FRAMES_PER_BUFFER,
        )
        try:
            total = int(rate / FRAMES_PER_BUFFER * seconds)
            for i in range(total):
                if cancel and cancel():
                    raise CaptureCancelled("recording cancelled")
                frames.append(stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False))
                if progress and i % 4 == 0:
                    progress(min(1.0, (i + 1) / total))
        finally:
            stream.stop_stream()
            stream.close()
        if progress:
            progress(1.0)
    finally:
        pa.terminate()

    if len(frames) * FRAMES_PER_BUFFER / 48000 < 1.5:
        raise CaptureCancelled("not enough audio captured")

    out_dir = app_dir() / "recordings"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"rec_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))
    _prune(out_dir)
    return str(path)


def _prune(folder, keep: int = 10) -> None:
    try:
        files = sorted(folder.glob("rec_*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[keep:]:
            f.unlink(missing_ok=True)
    except Exception:
        pass


# ------------------------------------------------------------------ shazam
def _walk_urls(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _walk_urls(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_urls(v, out)
    elif isinstance(obj, str) and obj.startswith("http"):
        out.add(obj)


def extract_song_info(res: dict) -> Optional[SongResult]:
    matches = (res or {}).get("matches") or []
    if not matches:
        return None
    m = matches[0]
    track = m.get("track") or {}
    title = track.get("title") or m.get("title") or "Unknown title"
    artist = track.get("subtitle") or track.get("artist") or ""
    images = track.get("images") or {}
    cover = images.get("coverarthq") or images.get("coverart") or ""
    genres = track.get("genres") or {}
    genre = genres.get("primary") if isinstance(genres, dict) else ""
    urls: set[str] = set()
    _walk_urls(m, urls)
    youtube = next((u for u in urls if "youtube.com/watch" in u or "youtu.be/" in u), "")
    apple = next((u for u in urls if "music.apple.com" in u or "itunes.apple.com" in u), "")
    shazam_url = m.get("url") or track.get("url") or ""
    if not shazam_url:
        shazam_url = next((u for u in urls if "shazam.com" in u), "")
    return SongResult(
        title=title,
        artist=artist,
        cover_url=cover,
        youtube_url=youtube,
        shazam_url=shazam_url,
        apple_url=apple,
        genre=genre or "",
        raw=m,
    )


def identify_song(wav_path: str) -> Optional[SongResult]:
    """Shazam a wav file. Returns None when nothing matched."""
    from shazamio import Shazam

    async def _go():
        return await Shazam().recognize(wav_path)

    try:
        res = asyncio.run(_go())
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "not found" in msg or "no match" in msg:
            return None
        raise AudioError(f"Shazam request failed: {e}") from e
    if not isinstance(res, dict):
        return None
    song = extract_song_info(res)
    if song is None:
        log.info("shazam: no match (%s)", list(res.keys()))
    return song


def fetch_cover(url: str, timeout: int = 20) -> bytes:
    import requests

    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Glimpse/0.1"})
        r.raise_for_status()
        return r.content
    except Exception as e:  # noqa: BLE001
        log.info("cover fetch failed: %s", e)
        return b""
