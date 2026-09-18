# Glimpse 0.4.0 — every language, screenshots, and region recording

## Read text in (almost) any language — including the snips that said "no text found"

Text recognition no longer depends on which languages you ticked. With **Always try every
installed language** (on by default) a snip is read by **one pass per writing system** —
Han, Hangul, Arabic, Cyrillic, Devanagari, Hebrew, Greek, Thai, Latin … — using every
language you have data for, and the results are ranked by Tesseract's own per-word
confidence. A two-character Chinese label (中文) now reads correctly even though neither
Chinese nor Japanese was enabled.

- Verified by test: Chinese, Japanese, Korean, Russian, Greek, Hebrew, Hindi, Arabic, Urdu
  and Turkish snips are each read by the right model, at 85–96 % confidence, ~0.6 s per snip.
- Han/Kana spacing is joined back up (`中 文` → `中文`); Hangul keeps its word spaces.
- The engine chain is also smarter about *which* engine to believe: if Tesseract read a
  script Windows has no language pack for, its (Latin) transliteration no longer wins.
- Options → Text (OCR) shows the new setting, plus per-language download state as before.

## Save screenshots

- New **Save** button in the capture bar and **Save screenshot…** in the tray / Home window.
- Saves to `Pictures\Glimpse\Screenshot_<date>_<time>.png` (folder configurable), with a
  toast that opens the folder. Same-second captures get `-2`, `-3`, … so nothing is lost.

## Record a snip — short videos, trimmed in seconds

- **Ctrl+Alt+R** (or tray → *Record region…*, or the **Record** button in the capture bar)
  then drag the area you want on screen.
- Recording shows a red frame around the region and a live **REC 00:07 · Stop** pill placed
  *outside* the region; the same hotkey or the Stop button ends it.
- Files are H.264 MP4 at native resolution (recorded through ffmpeg), saved to
  `Videos\Glimpse`, with an optional **system audio** track (Options → General).
- The clip window opens automatically: scrub any frame, **Trim & save as…** (instant, no
  re-encode), **Open**, **Open folder**, **Copy path**, **Delete**, and **Send frame to
  Google Lens** for the visual search of what is on screen.
- Needs ffmpeg on PATH (or `ffmpeg.exe` next to Glimpse). The Options window tells you which
  it found; without it you get a clear message instead of a broken recording.

## Multi-monitor fix: no more zoomed secondary screens

The picker used to be one window spanning the whole desktop; Windows scales such a window to
one monitor's DPI, which made monitors with a different scaling factor look zoomed in. It is
now **one freeze-frame window per screen**, each at its own resolution and DPI, and selections
can still span monitors. Verified live: inside the selection the screen is pixel-identical to
what was on it, outside it is dimmed — on a 1.5× primary plus two 1.0× monitors.

## Also

- New hotkey **Ctrl+Alt+R** (record) — configurable like the others in Options → Hotkeys.
- Tray: *Save screenshot…*, *Record region…* / *Stop recording*, *Clips folder…*.
- Self test now covers the multi-script OCR path and a real recording round-trip, so every
  build proves both before it ships.
