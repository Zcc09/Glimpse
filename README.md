# Glimpse — Google Lens for Windows

Snip any area of the screen and act on it: read the text, translate it, search it visually,
scan a QR/barcode — or identify the song that's playing. Native Windows app, tray-resident,
with a Snipping-Tool style region selector and global hotkeys.

```
Ctrl+Alt+L   capture area  →  Text / Translate / Search / Code / Copy
Ctrl+Alt+T   capture area  →  read + translate immediately
Ctrl+Alt+S   capture area  →  visual search immediately
Ctrl+Alt+M   identify the song playing on the system
```

## What it does

| Feature | How |
|---|---|
| **Text (OCR)** | Windows.Media.Ocr via `winsdk` — built in, no extra installs. Tesseract is used automatically when installed. |
| **Translate** | Engine chain: Google (clients5) → MyMemory → deep-translator Google. Auto-swap: Arabic ⇄ your partner language, or pin a fixed target. |
| **Visual search** | Google Lens reverse-image upload, opens the results in your browser. Yandex Images as an alternative engine. |
| **Codes** | QR / barcodes decoded with zxing-cpp; copy or open links. |
| **Song ID** | Records system audio through WASAPI loopback (or the mic) and asks Shazam — cover art and links in the result window. |
| **History** | Every capture is stored locally (SQLite + PNGs) with search, filters and per-entry actions. |
| **Solve** | When the selected text looks like an expression, a Solve button opens WolframAlpha. |

The cropped area is copied to your clipboard after every capture (Snipping-Tool behaviour,
can be turned off). Press Enter or double-click to run your default action; the action bar
appears right under the selection.

## Install

Run **`Glimpse-Setup.exe`** — a wizard with the usual pages (Welcome → Destination →
Start Menu → Tasks → Ready → Installing → Finish). It installs per-user into
`%LOCALAPPDATA%\Programs\Glimpse` (no administrator prompt), creates Desktop/Start Menu
shortcuts, and registers an Add/Remove Programs entry that runs
`Glimpse.exe --uninstall` (your settings/history are kept).

Silent/automated use:

```
Glimpse-Setup.exe --silent --install-dir <path> --no-desktop-shortcut --no-startmenu-shortcut --json
Glimpse-Setup.exe --silent --uninstall
```

From source:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python.exe -m glimpse
```

## Self test / CLI

The app verifies its own stack headlessly (OCR, QR, history, translation, Lens/Yandex, audio):

```bash
Glimpse.exe --selftest --selftest-out report.json        # add --audio-test for a record+Shazam roundtrip
Glimpse.exe --ocr shot.png
Glimpse.exe --translate "hello" --to ar
Glimpse.exe --songid --seconds 8
Glimpse.exe --capture --out screen.png
Glimpse.exe --uninstall [--silent]
```

The frozen build attaches a console automatically when a flag is used, and the report file is
written even when stdout is unavailable.

## Data & settings

Everything lives in `%APPDATA%\Glimpse` (`GLIMPSE_HOME` overrides it — used for portable
copies and by the tests):

- `settings.json` — hotkeys, engines, languages, behaviour
- `history.db` + `captures/` — history entries and images
- `recordings/` — the last few audio captures
- `glimpse.log` — rotating log (Settings → Open log)

## Tests

```bash
.venv/Scripts/python.exe -m pytest                      # pipeline + UI smoke (17 tests, real network/audio where needed)
.venv/Scripts/python.exe -m pytest -m live_desktop -v   # 3 live-desktop E2E tests (open windows for ~20 s)
```

- `tests/test_pipeline.py` — every backend for real: Windows OCR on rendered text, QR decode,
  capture/crop DPR math, history, settings, live translation, Lens/Yandex upload, WASAPI
  loopback capture of a playing tone, Shazam roundtrip.
- `tests/test_ui_smoke.py` — constructs and paints every window (and draws every icon).
- `tests/test_e2e_desktop.py` — drives the real app: posts a real `WM_HOTKEY` at the app's
  sink window, drags a real selection over a real window with synthetic mouse input, presses
  Enter / clicks the action-bar button, and asserts what landed in the history DB.
  Injected keys cannot trigger `RegisterHotKey` on Windows 11, so the OS key-matching itself
  is verified by pressing the hotkey by hand — everything after it is exercised for real.

Packaging / deployment:

```bash
bash packaging/release_check.sh        # assets → app → frozen selftest → Setup.exe → install/uninstall test
.venv/Scripts/python.exe packaging/install_test.py [path-to-Setup.exe]
```

`install_test.py` installs into a temp folder (no shortcuts), runs the **installed** exe's
self test and a real desktop capture, then uninstalls and checks the folder + registry entry
are gone and your data survived.

## Layout

- `glimpse/app.py` — tray icon, hotkeys, capture flow; `overlay.py` the selector + action bar
- `glimpse/ocr/`, `translate.py`, `visual.py`, `qrscan.py`, `audio.py`, `history.py` — the backends
- `glimpse/ui/` — result, song, history, settings windows, toasts, listening pill
- `packaging/` — PyInstaller specs, setup wizard, version info, release check
- `scripts/probe_env.py`, `scripts/probe_hotkey.py` — capability probes for a new machine

## Troubleshooting

- **No OCR text** — Windows needs a language pack with OCR: Settings → Time & language →
  Language & region → Add a language, with "Optical character recognition".
- **Song not identified** — make sure the song plays through your default output device, or
  switch to Microphone in Settings; a longer "listen duration" helps.
- **A translation engine fails** — Google's free endpoints rate-limit some networks; Glimpse
  falls back automatically (see `glimpse.log`). "Open in Google Translate" always works.
- **Hotkey refused** — Settings shows which combination Windows rejected; pick another.
