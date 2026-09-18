Glimpse 0.2.0 — tray menu, Home window, and in-app updates.

**New in this release**
- Tray menu now has **Open** (a Home window), **Options…**, **Run at startup**, **Check for updates…** and **Exit**.
- **Home window** — big buttons for Capture / Translate / Visual search / Song ID / History / Options, hotkey hints, engine status and an update row.
- **Updates** — Glimpse checks this repository's latest release (at startup and on demand), shows the release notes, downloads `Glimpse-Setup.exe` and installs it in place (silent, relaunches). Portable copies get the download + a folder shortcut instead. Configure the repo in Options → Updates.
- Options gained an **Updates** group (auto-check on start, repository, Check now).
- The installer now updates an existing installation **in place** even in silent mode (used by the in-app updater).

**Install**
Run `Glimpse-Setup.exe` — per-user install (no UAC), Desktop/Start Menu shortcuts, Add/Remove Programs entry (`Glimpse.exe --uninstall` keeps your settings/history).
`Glimpse-0.2.0-portable.zip` is a no-install folder build (slower first start, no shortcuts).

**Hotkeys** — Ctrl+Alt+L capture · Ctrl+Alt+T capture & translate · Ctrl+Alt+S visual search · Ctrl+Alt+M identify song.

**Verification for this build** (all measured on the build machine)
- Frozen app self test — 8/8 steps: OCR (`Glimpse selftest 4242`), QR decode, history, translate EN→AR/AR→EN, Google Lens upload, Yandex upload, WASAPI loopback record + Shazam roundtrip.
- Deployment test — 15/15 twice (wizard from source and the frozen Setup.exe): silent install → installed exe `--version`/`--selftest`/`--capture` (1.8 MB desktop PNG) → uninstall → folder + Add/Remove entry gone, user data kept.
- Wizard walk test — 14/14 twice: page order, footer on-screen on every page, no stray modals, real install, installed app runs, clean uninstall.
- `pytest` — 33 tests (pipeline, UI smoke, update checker) plus 3 live-desktop E2E tests driving real hotkeys, a real mouse drag and the action bar.

**Note:** the in-app updater exists from 0.2.0 — install 0.2.0 once and future releases will arrive through *Check for updates…*.
