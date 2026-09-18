# Glimpse 0.5.0 — no more flashing windows, and GPU recordings up to 60 fps

## The flashing windows are gone

You were right that something was wrong: while OCR ran, **a console window flashed for every
Tesseract pass** — and 0.4.x made passes plentiful, so translating gave you "a bunch of windows
popping out and closing" until the text appeared.

The cause: Glimpse is a windowed app with no console of its own, and every console program it
started (tesseract, ffmpeg, ffprobe) therefore got a **new console window** unless explicitly
told not to. Every call now goes through one helper (`glimpse/proc.py`) that passes
`CREATE_NO_WINDOW` plus a hidden-startup-info, and a test suite keeps it that way:

- a test reproduces the bug (from a console-less parent, unflagged children *do* flash a
  window) and proves the fix (the same run through the helper shows none),
- a static guard fails the build if any future `subprocess` call bypasses the helper,
- and a live test runs the **built app** through an OCR pass while counting console windows.

## Recording: 60 fps, GPU capture, AV1 / HEVC / H.264

- **Frame rate up to 60 fps** (15 / 24 / 30 / 60 in Options).
- **Codec choice**: Auto, **AV1**, **HEVC (H.265)** or H.264 — Auto picks the best available,
  preferring AV1.
- **Hardware acceleration both ways**:
  - *Capture*: the region is grabbed through **Desktop Duplication** (`ddagrab`) inside ffmpeg,
    so no Python work happens per frame at all — that is what makes a real 60 fps possible.
  - *Encoding*: **NVENC / QSV / AMF** when present (`av1_nvenc`, `hevc_nvenc`, `h264_nvenc`, …),
    with libx264/libx265/SVT-AV1 as the software fallback.
- Options → General shows what your machine will actually use, e.g.
  *"Detected: av1_nvenc (hardware) · GPU capture (Desktop Duplication)"*, and the recording
  toast repeats it while recording.
- If GPU capture is unavailable, Glimpse falls back to CPU grabs **and keeps the timeline
  honest**: when the machine cannot grab at the requested rate, frames are repeated instead of
  writing a clip that plays back faster than reality (that bug is now a test).
- The clip window shows the codec, and trimming still works instantly for every codec.

Measured on an RTX 5080, 4-second 960×540 region: **AV1 hardware, 59 fps, 300 frames**, and
HEVC hardware likewise; the CPU fallback records true real-time duration at 60 fps.
