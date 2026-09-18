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

from . import proc as proc_mod
from .log import log
from .paths import resource_path

MAX_SECONDS_LIMIT = 3600
MAX_FPS = 60


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


# ------------------------------------------------------------------ encoders
# Tried in this order per codec family: hardware encoders first, then the software
# fallbacks that always work (slower, more CPU).
ENCODER_CHAIN: dict[str, tuple[tuple[str, str], ...]] = {
    "av1": (("av1_nvenc", "hw"), ("av1_qsv", "hw"), ("av1_amf", "hw"),
            ("libsvtav1", "sw"), ("libaom-av1", "sw")),
    "hevc": (("hevc_nvenc", "hw"), ("hevc_qsv", "hw"), ("hevc_amf", "hw"), ("libx265", "sw")),
    "h264": (("h264_nvenc", "hw"), ("h264_qsv", "hw"), ("h264_amf", "hw"), ("libx264", "sw")),
}
CODEC_LABELS = {"auto": "Auto", "av1": "AV1", "hevc": "HEVC (H.265)", "h264": "H.264"}
_CACHE: dict[str, object] = {}


def available_encoders() -> dict[str, str]:
    """{encoder_name: 'hw'|'sw'} for every video encoder this ffmpeg offers."""
    exe = find_ffmpeg()
    if not exe:
        return {}
    if _CACHE.get("encoders_exe") == exe:
        return _CACHE.get("encoders") or {}  # type: ignore[return-value]
    out: dict[str, str] = {}
    try:
        text = proc_mod.run([exe, "-hide_banner", "-encoders"], capture_output=True,
                            timeout=30, check=False).stdout.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        log.warning("could not list ffmpeg encoders: %s", e)
        return {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith("V"):
            continue
        name = parts[1]
        out[name] = "hw" if name.endswith(("_nvenc", "_qsv", "_amf", "_vaapi", "_videotoolbox")) else "sw"
    _CACHE["encoders_exe"] = exe
    _CACHE["encoders"] = out
    return out


def pick_encoder(codec: str = "auto", prefer_hw: bool = True) -> tuple[str | None, bool]:
    """Best encoder for a codec family here → (encoder name, is_hardware).

    ``auto`` prefers AV1, then HEVC, then H.264 — hardware when the GPU can do it, software
    otherwise, and H.264 (or anything this ffmpeg has) as the last resort.
    """
    have = available_encoders()
    if not have:
        return (None, False)
    families = ("av1", "hevc", "h264") if codec in ("", "auto", None) else (codec,)
    for family in families:
        for name, kind in ENCODER_CHAIN.get(family, ()):
            if name in have and (kind != "hw" or prefer_hw):
                return name, have.get(name) == "hw"
    for name in ("libx264", "h264_nvenc", "mpeg4"):
        if name in have:
            return name, have.get(name) == "hw"
    return (None, False)


def encoder_args(encoder: str) -> list[str]:
    """Codec/preset/rate-control flags with balanced quality for this encoder."""
    if encoder.endswith("_nvenc"):
        cq = {"av1_nvenc": 32, "hevc_nvenc": 28, "h264_nvenc": 26}.get(encoder, 28)
        return ["-c:v", encoder, "-preset", "p5", "-tune", "hq", "-rc", "vbr",
                "-cq", str(cq), "-b:v", "0", "-pix_fmt", "yuv420p"]
    if encoder.endswith("_qsv"):
        return ["-c:v", encoder, "-preset", "medium", "-global_quality", "26", "-pix_fmt", "nv12"]
    if encoder.endswith("_amf"):
        return ["-c:v", encoder, "-quality", "balanced", "-rc", "cqp",
                "-qp_i", "24", "-qp_p", "26", "-pix_fmt", "yuv420p"]
    if encoder == "libx265":
        return ["-c:v", encoder, "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                "-tag:v", "hvc1"]
    if encoder == "libsvtav1":
        return ["-c:v", encoder, "-preset", "10", "-crf", "34", "-pix_fmt", "yuv420p"]
    if encoder == "libaom-av1":
        return ["-c:v", encoder, "-cpu-used", "6", "-crf", "34", "-b:v", "0", "-pix_fmt", "yuv420p"]
    if encoder == "libx264":
        return ["-c:v", encoder, "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    return ["-c:v", encoder, "-pix_fmt", "yuv420p"]


def ddagrab_available() -> bool:
    """Desktop Duplication capture (GPU grabs instead of CPU screen grabs) available?"""
    exe = find_ffmpeg()
    if not exe:
        return False
    if _CACHE.get("filters_exe") == exe:
        return bool(_CACHE.get("ddagrab"))
    ok = False
    try:
        text = proc_mod.run([exe, "-hide_banner", "-filters"], capture_output=True,
                            timeout=30, check=False).stdout.decode("utf-8", "replace")
        ok = "ddagrab" in text
    except Exception as e:  # noqa: BLE001
        log.warning("could not list ffmpeg filters: %s", e)
    _CACHE["filters_exe"] = exe
    _CACHE["ddagrab"] = ok
    return ok


def _even(value: int) -> int:
    return value - (value % 2)


def gpu_capture_args(rect, fps: int) -> tuple[list[str], bool]:
    """Input args for a Desktop-Duplication capture of ``rect`` → (args, ok).

    The region is mapped to the monitor that contains it and scaled by that monitor's DPR,
    because ddagrab offsets are physical pixels within one DXGI output. Even offsets/sizes
    keep yuv420p happy.
    """
    try:
        from PySide6.QtGui import QGuiApplication
    except Exception:  # noqa: BLE001
        return ([], False)
    screens = QGuiApplication.screens()
    if not screens:
        return ([], False)
    screen = QGuiApplication.screenAt(rect.center()) or screens[0]
    try:
        index = screens.index(screen)
    except ValueError:
        index = 0
    dpr = float(screen.devicePixelRatio() or 1.0)
    geo = screen.geometry()
    x = _even(int(round((rect.left() - geo.left()) * dpr)))
    y = _even(int(round((rect.top() - geo.top()) * dpr)))
    w = _even(int(round(rect.width() * dpr)))
    h = _even(int(round(rect.height() * dpr)))
    if w < 2 or h < 2:
        return ([], False)
    source = (
        f"ddagrab=output_idx={index}:framerate={max(5, min(60, int(fps)))}"
        f":video_size={w}x{h}:offset_x={x}:offset_y={y}:draw_mouse=0"
    )
    return (
        ["-init_hw_device", "d3d11va=dx", "-f", "lavfi", "-i", source,
         "-vf", "hwdownload,format=bgra"],
        True,
    )


def clip_codec(path: str | Path) -> str:
    """Codec name of a clip's video stream ('av1'/'hevc'/'h264'… or '' when unknown)."""
    probe = find_ffprobe()
    if not probe:
        return ""
    try:
        out = proc_mod.run(
            [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=20, check=False,
        )
        return out.stdout.decode("utf-8", "replace").strip().splitlines()[:1][0] if out.stdout else ""
    except Exception:  # noqa: BLE001
        return ""


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
        out = proc_mod.run(
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
        out = proc_mod.run(cmd, capture_output=True, timeout=60, check=False)
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
        out = proc_mod.run(cmd, capture_output=True, timeout=120, check=False)
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
        fps: int = 30,
        max_seconds: int = 300,
        audio: bool = False,
        audio_source: str = "system",
        audio_device: str = "",
        codec: str = "auto",
        hardware: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.rect = QRect(rect).normalized()
        self.path = str(path)
        self.fps = max(5, min(MAX_FPS, int(fps)))
        self.max_seconds = max(5, min(MAX_SECONDS_LIMIT, int(max_seconds)))
        self.audio = bool(audio)
        self.audio_source = audio_source
        self.audio_device = audio_device
        self.codec = codec or "auto"
        self.hardware = bool(hardware)
        self.encoder, self.encoder_is_gpu = pick_encoder(self.codec, prefer_hw=self.hardware)
        if not self.encoder:
            self.encoder, self.encoder_is_gpu = "libx264", False
        self.backend = ""          # "gpu" (Desktop Duplication) or "cpu" (screen grabs)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0
        self._error = ""
        self._written = 0

    def describe(self) -> str:
        """One line for the UI/log: encoder, whether it is the GPU, capture path."""
        where = {"gpu": "GPU capture", "cpu": "CPU capture"}.get(self.backend, "")
        hw = "hardware" if self.encoder_is_gpu else "software"
        return f"{self.encoder} ({hw}){' · ' + where if where else ''} · {self.fps} fps"

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
        # GPU capture first (Desktop Duplication inside ffmpeg — no Python in the frame
        # loop, which is what makes 60 fps and hardware encoders worthwhile), then the
        # grab-and-pipe fallback for machines where that is unavailable.
        if self.hardware and ddagrab_available():
            capture_args, ok = gpu_capture_args(self.rect, self.fps)
            if ok and self._run_gpu(exe, capture_args):
                return
            log.warning("recorder: GPU capture did not work — falling back to CPU screen grabs")
        self.backend = "cpu"
        self._run_pump(exe)

    def _run_gpu(self, exe: str, capture_args: list[str]) -> bool:
        """Record via Desktop Duplication. Returns False when it could not be done."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        audio_path = str(Path(self.path).with_suffix(".wav")) if self.audio else None
        audio_thread = None
        if self.audio:
            audio_thread = threading.Thread(target=self._audio_worker, args=(audio_path,), daemon=True)
            audio_thread.start()

        cmd = [
            exe, "-hide_banner", "-v", "error", *capture_args,
            *encoder_args(self.encoder or "libx264"),
            "-movflags", "+faststart", "-t", str(self.max_seconds), self.path,
        ]
        if os.path.exists(self.path):
            try:
                os.unlink(self.path)
            except OSError:
                pass
        self.backend = "gpu"
        log.info("recording (GPU) %s → %s (%s)", self.rect.getRect(), self.path, self.describe())
        proc = proc_mod.popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        def _join_audio() -> None:
            if audio_thread is None:
                return
            self._stop.set()          # the monitor loop ended: stop capturing audio too
            audio_thread.join(timeout=4)
            if audio_path and os.path.isfile(audio_path):
                if not self._mux_audio(self.path, audio_path):
                    log.warning("could not mux audio; the video is still fine")
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

        last_tick = 0.0
        err = b""
        try:
            while not self._stop.is_set():
                if proc.poll() is not None:
                    break              # ffmpeg gave up (unsupported output, busy device…)
                now = time.monotonic()
                elapsed = now - self._started
                if elapsed >= self.max_seconds:
                    log.info("recorder: reached the %ds limit", self.max_seconds)
                    break
                if elapsed - last_tick >= 0.25:
                    last_tick = elapsed
                    self.tick.emit(elapsed)
                time.sleep(0.05)
        finally:
            try:
                if proc.poll() is None:
                    proc.stdin.write(b"q")     # graceful quit: finalises the container
                    proc.stdin.flush()
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                _, err = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                _, err = proc.communicate()

        duration = probe_duration(self.path)
        if proc.returncode != 0 or duration <= 0.2:
            text = (err or b"").decode("utf-8", "replace").strip()[:300]
            log.warning("GPU recording failed rc=%s: %s", proc.returncode, text or "no frames written")
            _join_audio()
            try:
                os.unlink(self.path)
            except OSError:
                pass
            return False

        _join_audio()
        self._written = max(self._written, int(duration * self.fps))
        self.tick.emit(self.elapsed())
        log.info("recording finished: %s (%s, %.1fs)", self.path, clip_codec(self.path) or self.encoder, duration)
        self.finished.emit(self.path)
        return True

    def _run_pump(self, exe: str) -> None:
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
            "-an", *encoder_args(self.encoder or "libx264"),
            "-movflags", "+faststart", self.path,
        ]
        log.info("recording %s → %s (%dx%d, %s)", self.rect.getRect(), self.path, w, h, self.describe())
        proc = proc_mod.popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

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
                    # Keep the timeline honest. When the machine cannot grab at the requested
                    # rate (a 1440x810 grab+pack costs ~50 ms here ≈ 19 fps at 60 fps
                    # requested), declaring 60 fps anyway produced a clip that played three
                    # times too fast. Repeat the last frame to fill the gap instead.
                    target = int((time.monotonic() - self._started) * self.fps)
                    repeated = 0
                    while self._written < target and repeated <= self.fps:
                        proc.stdin.write(payload)
                        self._written += 1
                        repeated += 1
                    if repeated > self.fps:
                        log.debug("grab rate below target; timeline is behind by %d frames",
                                  target - self._written)
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
            out = proc_mod.run(cmd, capture_output=True, timeout=180, check=False)
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
