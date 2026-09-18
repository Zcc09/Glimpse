"""Region screen recording (frames piped to ffmpeg) and clip helpers.

The recorder grabs the selected region live at native resolution and streams raw BGRA
frames into ffmpeg, which encodes H.264 MP4. Stop whenever you like: the file is
finalised and handed to the clip window for trimming or sending to Lens.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage

from .log import log
from .paths import resource_path

MAX_SECONDS_LIMIT = 3600


# ------------------------------------------------------------------ ffmpeg
def _winget_globs() -> list[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
    ]


def find_ffmpeg() -> str | None:
    """Bundled copy, then PATH, then the usual installs (winget, chocolatey, scoop)."""
    for rel in ("ffmpeg/ffmpeg.exe", "bin/ffmpeg.exe"):
        try:
            cand = Path(resource_path(rel))
            if cand.is_file():
                return str(cand)
        except Exception:
            pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    candidates: list[str] = []
    for pattern in _winget_globs():
        candidates += glob.glob(pattern, recursive=True)
    local = os.environ.get("LOCALAPPDATA", "")
    candidates += [
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return cand
    return None


def find_ffprobe() -> str | None:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        cand = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if cand.is_file():
            return str(cand)
    return None


def ffmpeg_available() -> bool:
    return bool(find_ffmpeg())


# ------------------------------------------------------------------ raw frames
def _bgra_bytes(image: QImage) -> tuple[bytes, int, int]:
    """Tightly packed BGRA bytes with even dimensions (yuv420p needs even w/h)."""
    img = image.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width() & ~1, img.height() & ~1  # even
    if w < 2 or h < 2:
        raise RuntimeError(f"region too small to record ({image.width()}x{image.height()})")
    if w != img.width() or h != img.height():
        img = img.copy(0, 0, w, h)
    stride = img.bytesPerLine()
    bits = bytes(img.constBits())
    if stride == w * 4:
        return bits, w, h
    # repack row by row (QImage pads scanlines to 4 bytes; ours are 4-byte aligned already)
    rows = [bits[y * stride : y * stride + w * 4] for y in range(h)]
    return b"".join(rows), w, h


# ------------------------------------------------------------------ helpers
def probe_duration(path: str | Path) -> float:
    """Length of a clip in seconds (0.0 when unknown)."""
    probe = find_ffprobe()
    if not probe:
        return 0.0
    try:
        out = subprocess.run(
            [
                probe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True, timeout=20, check=False,
        )
        return max(0.0, float(out.stdout.decode("utf-8", "replace").strip() or 0))
    except Exception as e:  # noqa: BLE001
        log.warning("ffprobe failed on %s: %s", path, e)
        return 0.0


def frame_at(path: str | Path, seconds: float = 0.0) -> QImage | None:
    """One frame of a clip as a QImage (used for previews and Lens uploads)."""
    exe = find_ffmpeg()
    if not exe:
        return None
    cmd = [exe, "-v", "error", "-ss", f"{max(0.0, seconds):.3f}", "-i", str(path),
           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except Exception as e:  # noqa: BLE001
        log.warning("ffmpeg frame grab failed: %s", e)
        return None
    if out.returncode != 0 or not out.stdout:
        log.warning("ffmpeg frame grab returned %d bytes (rc=%s)", len(out.stdout or b""), out.returncode)
        return None
    img = QImage()
    if not img.loadFromData(out.stdout):
        return None
    return img


def trim_clip(src: str | Path, dst: str | Path, start: float, end: float) -> bool:
    """Cut [start, end] out of a clip without re-encoding (keyframe-accurate enough)."""
    exe = find_ffmpeg()
    if not exe:
        return False
    duration = max(0.1, float(end) - float(start))
    cmd = [
        exe, "-y", "-v", "error", "-ss", f"{max(0.0, float(start)):.3f}", "-i", str(src),
        "-t", f"{duration:.3f}", "-c", "copy", "-avoid_negative_ts", "make_zero", str(dst),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    except Exception as e:  # noqa: BLE001
        log.warning("ffmpeg trim failed: %s", e)
        return False
    if out.returncode != 0:
        log.warning("ffmpeg trim rc=%s: %s", out.returncode, out.stderr.decode("utf-8", "replace")[:300])
        return False
    return Path(dst).is_file() and Path(dst).stat().st_size > 0


# ------------------------------------------------------------------ recorder
class Recorder(QObject):
    """Records a screen region to MP4 until stopped."""

    tick = Signal(float)      # elapsed seconds, ~4x per second
    finished = Signal(str)    # path to the mp4
    failed = Signal(str)

    def __init__(
        self,
        rect: QRect,
        path: str | Path,
        fps: int = 15,
        max_seconds: int = 300,
        audio: bool = False,
        audio_source: str = "system",
        audio_device: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.rect = QRect(rect).normalized()
        self.path = str(path)
        self.fps = max(5, min(30, int(fps)))
        self.max_seconds = max(5, min(MAX_SECONDS_LIMIT, int(max_seconds)))
        self.audio = bool(audio)
        self.audio_source = audio_source
        self.audio_device = audio_device

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0
        self._error = ""
        self._written = 0

    # ------------------------------------------------------------ control
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def elapsed(self) -> float:
        return (time.monotonic() - self._started) if self._started else 0.0

    def frames_written(self) -> int:
        return self._written

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True, name="glimpse-recorder")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float = 30.0) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    # ------------------------------------------------------------ capture
    def _audio_worker(self, path: str) -> None:
        """Record loopback/mic audio while the video runs (best effort)."""
        try:
            import pyaudiowpatch as pyaudio

            from .audio import FRAMES_PER_BUFFER, _pick_device

            pa = pyaudio.PyAudio()
            try:
                info = _pick_device(pa, self.audio_source, self.audio_device)
                rate = int(info.get("defaultSampleRate", 48000))
                channels = min(2, int(info.get("maxInputChannels", 2) or 2))
                stream = pa.open(
                    format=pyaudio.paInt16, channels=channels, rate=rate,
                    frames_per_buffer=FRAMES_PER_BUFFER, input=True, input_device_index=int(info["index"]),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("audio capture unavailable (%s) — recording video only", e)
                pa.terminate()
                return
            try:
                with wave.open(path, "wb") as w:
                    w.setnchannels(channels)
                    w.setsampwidth(2)
                    w.setframerate(rate)
                    while not self._stop.is_set():
                        try:
                            w.writeframes(stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False))
                        except Exception:  # noqa: BLE001
                            break
            finally:
                stream.stop_stream()
                stream.close()
                pa.terminate()
        except Exception as e:  # noqa: BLE001
            log.warning("audio recording failed: %s", e)

    def _run(self) -> None:
        exe = find_ffmpeg()
        if not exe:
            self._error = "ffmpeg was not found (install it or bundle it next to Glimpse)"
            log.error("recorder: %s", self._error)
            self.failed.emit(self._error)
            return

        from .capture import grab_region_device

        # first frame decides the geometry
        try:
            first = grab_region_device(self.rect)
            data, w, h = _bgra_bytes(first)
        except Exception as e:  # noqa: BLE001
            self._error = f"could not capture the region: {e}"
            log.error("recorder: %s", self._error)
            self.failed.emit(self._error)
            return

        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        audio_path = str(Path(self.path).with_suffix(".wav")) if self.audio else None
        audio_thread = None
        if self.audio:
            audio_thread = threading.Thread(target=self._audio_worker, args=(audio_path,), daemon=True)
            audio_thread.start()

        cmd = [
            exe, "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{w}x{h}", "-r", str(self.fps), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", self.path,
        ]
        log.info("recording %s → %s (%dx%d @%dfps)", self.rect.getRect(), self.path, w, h, self.fps)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        interval = 1.0 / self.fps
        next_at = time.monotonic()
        last_tick = 0.0
        try:
            proc.stdin.write(data)
            self._written += 1
            while not self._stop.is_set():
                now = time.monotonic()
                if now - self._started >= self.max_seconds:
                    log.info("recorder: reached the %ds limit", self.max_seconds)
                    break
                if now < next_at:
                    time.sleep(min(0.02, next_at - now))
                    continue
                next_at += interval
                if next_at < now:  # fell behind: do not try to catch up
                    next_at = now + interval
                try:
                    frame = grab_region_device(self.rect)
                    payload, fw, fh = _bgra_bytes(frame)
                    if (fw, fh) != (w, h):
                        continue  # layout changed mid-recording (resolution/DPI switch)
                    proc.stdin.write(payload)
                    self._written += 1
                except Exception as e:  # noqa: BLE001
                    log.debug("frame skipped: %s", e)
                el = now - self._started
                if el - last_tick >= 0.25:
                    last_tick = el
                    self.tick.emit(el)
        except Exception as e:  # noqa: BLE001
            self._error = str(e)
            log.error("recorder loop failed: %s", e)
        finally:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                _, err = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                err = b"timeout finalising the file"
            if proc.returncode != 0:
                self._error = (err or b"").decode("utf-8", "replace")[:300] or "ffmpeg failed"
                log.error("recorder: ffmpeg rc=%s %s", proc.returncode, self._error)

            if audio_thread is not None:
                # the audio thread stops on the same flag; give it a moment, then mux
                audio_thread.join(timeout=3)
                if not self._error and audio_path and os.path.isfile(audio_path):
                    if not self._mux_audio(self.path, audio_path):
                        log.warning("could not mux audio; the video is still fine")
                    try:
                        os.unlink(audio_path)
                    except OSError:
                        pass

        self.tick.emit(self.elapsed())
        if self._error:
            self.failed.emit(self._error)
        else:
            log.info("recording finished: %s (%d frames, %.1fs)", self.path, self._written, self.elapsed())
            self.finished.emit(self.path)

    def _mux_audio(self, video: str, audio: str) -> bool:
        exe = find_ffmpeg()
        if not exe:
            return False
        tmp = str(Path(video).with_name(Path(video).stem + "-mux.mp4"))
        cmd = [
            exe, "-y", "-v", "error", "-i", video, "-i", audio,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", tmp,
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=180, check=False)
        except Exception as e:  # noqa: BLE001
            log.warning("mux failed: %s", e)
            return False
        if out.returncode != 0 or not os.path.isfile(tmp):
            log.warning("mux rc=%s: %s", out.returncode, out.stderr.decode("utf-8", "replace")[:200])
            return False
        try:
            os.replace(tmp, video)
        except OSError:
            return False
        return True
