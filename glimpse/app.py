"""Glimpse application: tray icon, global hotkeys, capture flow, windows."""
from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QTimer
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon, QWidget

from . import __app_name__, __version__, autostart, icons, update, util, visual
from .audio import fetch_cover, identify_song, record_wav
from .capture import grab_all, png_bytes
from .config import Settings
from .history import History
from .hotkeys import HotkeyManager
from .log import log, setup_logging
from .ocr import recognize
from .paths import app_dir
from .single_instance import SingleInstance
from .translate import translate_text
from .ui import theme as theme_mod
from .ui.history_window import HistoryWindow
from .ui.home_window import HomeWindow
from .ui.listening_pill import ListeningPill
from .ui.result_window import ResultWindow
from .ui.settings_window import SettingsWindow
from .ui.song_window import SongWindow
from .ui.toast import ToastManager
from .ui.update_dialog import UpdateDialog


class GlimpseApp(QObject):
    def __init__(self, qapp: QApplication, settings: Settings, single: SingleInstance | None = None, start_hidden: bool = False):
        super().__init__()
        self.qapp = qapp
        self.settings = settings
        self.single = single
        self.toasts = ToastManager(self)
        self.history = History(limit=settings.history_limit)
        self.overlay = None
        self._pill: ListeningPill | None = None
        self._song_windows: list[SongWindow] = []
        self.windows: list = []
        self.history_window: HistoryWindow | None = None
        self.settings_window: SettingsWindow | None = None
        self.home_window: HomeWindow | None = None
        self.update_dialog: UpdateDialog | None = None

        # hidden window that receives WM_HOTKEY messages
        self._hotkey_sink = QWidget()
        self._hotkey_sink.setWindowTitle(f"{__app_name__}HotkeySink")
        self._hotkey_sink.resize(1, 1)
        hwnd = int(self._hotkey_sink.winId())
        self.hotkeys = HotkeyManager(hwnd, self)
        self.hotkeys.triggered.connect(self._on_hotkey)
        qapp.installNativeEventFilter(self.hotkeys)

        self._build_tray()

        if single is not None:
            single.message.connect(self._on_instance_message)

        self._register_hotkeys()

        if not start_hidden:
            QTimer.singleShot(700, self._welcome)
        if settings.check_updates_on_start:
            QTimer.singleShot(4000, lambda: self.check_for_updates(interactive=False))

    # ---------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.tray_icon(), self)
        self.tray.setToolTip(f"{__app_name__} — capture: {self.settings.hotkeys.get('capture', '')}")
        menu = QMenu()
        mi = icons.tray_menu_icons()

        def add(key: str, label: str, cb, icon_override=None) -> QAction:
            a = QAction(icon_override or mi[key], label, self)
            a.triggered.connect(cb)
            menu.addAction(a)
            return a

        add("capture", "Open Glimpse", self.show_home, icon_override=icons.tile_icon(20))
        menu.addSeparator()
        add("capture", "Capture area…", lambda: self.start_capture())
        add("translate", "Capture & translate…", lambda: self.start_capture(immediate="translate"))
        add("visual", "Capture & visual search…", lambda: self.start_capture(immediate="visual"))
        add("songid", "Identify song…", lambda: self.identify_song())
        menu.addSeparator()
        add("history", "History…", self.show_history)
        add("settings", "Options…", self.show_settings)
        self.autostart_action = QAction(mi["settings"], "Run at startup", self)
        self.autostart_action.setCheckable(True)
        self.autostart_action.toggled.connect(self.toggle_autostart)
        menu.addAction(self.autostart_action)
        add("update", "Check for updates…", lambda: self.check_for_updates(interactive=True))
        add("about", "About", self.show_about)
        menu.addSeparator()
        add("quit", "Exit", self.quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._sync_autostart_menu()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_home()

    def _sync_autostart_menu(self) -> None:
        action = getattr(self, "autostart_action", None)
        if action is None:
            return
        enabled = autostart.is_enabled() if autostart.supported() else bool(self.settings.autostart)
        action.blockSignals(True)
        action.setChecked(enabled)
        action.blockSignals(False)

    def toggle_autostart(self, enabled: bool) -> None:
        if not autostart.supported():
            self.notify("Run at startup", "Available in the installed build (see Options).", kind="warn", timeout=5000)
            self._sync_autostart_menu()
            return
        if autostart.set_enabled(bool(enabled)):
            self.settings.autostart = bool(enabled)
            try:
                self.settings.save()
            except Exception:
                pass
            self.notify("Run at startup", "Glimpse will start with Windows." if enabled else "Glimpse will no longer start with Windows.",
                        kind="success", timeout=2500)
        else:
            self.notify("Run at startup", "Windows refused the startup entry.", kind="warn")
        self._sync_autostart_menu()

    # ---------------------------------------------------------------- hotkeys
    def _register_hotkeys(self) -> None:
        errors = self.hotkeys.set_hotkeys(self.settings.hotkeys)
        for action, err in errors.items():
            log.warning("hotkey %s: %s", action, err)
            self.notify("Hotkey not registered", err, kind="warn", timeout=6000)

    def _on_hotkey(self, action: str) -> None:
        log.info("hotkey pressed: %s", action)
        if action == "songid":
            self.identify_song()
            return
        if action == "translate":
            self.start_capture(immediate="translate")
            return
        if action == "visual":
            self.start_capture(immediate="visual")
            return
        self.start_capture()

    def _on_instance_message(self, message: str) -> None:
        if message == "capture":
            self.start_capture()
        elif message == "songid":
            self.identify_song()
        else:
            self.notify(f"{__app_name__} is already running", "Use the tray icon or the hotkeys.")

    # ---------------------------------------------------------------- capture
    def start_capture(self, immediate: str | None = None) -> None:
        log.info("capture starting (immediate=%s)", immediate)
        if self.overlay is not None:
            log.info("capture already in progress")
            return
        try:
            shot = grab_all()
        except Exception as e:  # noqa: BLE001
            log.error("screen grab failed: %s", e)
            self.notify("Capture failed", str(e), kind="error")
            return
        log.info("grabbed %d screen(s), virtual rect %s", len(shot.pieces), shot.virtual_rect)

        from .overlay import Overlay

        self.overlay = Overlay(shot, default_action=self.settings.default_action, immediate_action=immediate)
        self.overlay.action_chosen.connect(self._on_action)
        self.overlay.cancelled.connect(self._on_overlay_cancelled)
        self.overlay.destroyed.connect(lambda *_: self._clear_overlay())
        self.overlay.show()
        log.info("overlay shown")

    def _clear_overlay(self) -> None:
        self.overlay = None

    def _on_overlay_cancelled(self) -> None:
        log.info("capture cancelled")

    def _on_action(self, action: str, sel: QRect) -> None:
        overlay = self.overlay
        if overlay is None:
            return
        try:
            image = overlay.shot.crop(sel)
        except Exception as e:  # noqa: BLE001
            self.notify("Capture failed", str(e), kind="error")
            return
        finally:
            overlay.close()

        if self.settings.copy_image_on_capture or action == "copy":
            util.copy_image(image)

        if action == "text":
            self._action_text(image)
        elif action == "translate":
            self._action_translate(image)
        elif action == "visual":
            self._action_visual(image)
        elif action == "qr":
            self._action_qr(image)
        elif action == "copy":
            self.notify("Image copied", "The selected area is on your clipboard.", kind="success", timeout=2200)
        else:
            log.warning("unknown action %s", action)

    # ---------------------------------------------------------------- actions
    def _run_ocr(self, image: QImage, win: ResultWindow, on_text=None) -> None:
        s = self.settings
        util.run_bg(
            lambda: recognize(image, s.ocr_language, s.ocr_engine),
            on_ok=lambda res: self._ocr_done(win, res, on_text),
            on_err=lambda k, m, tb: win.set_error(f"{k}: {m}"),
            name="ocr",
        )

    def _ocr_done(self, win: ResultWindow, res, on_text) -> None:
        win.set_ocr(res)
        if on_text:
            on_text(res)

    def _action_text(self, image: QImage) -> None:
        win = ResultWindow(self, image, kind="text")
        self._track(win)
        win.set_busy("Reading text…")
        win.show()

        def text_ready(res) -> None:
            text = (res.text or "").strip()
            if not text:
                win.set_status("No text found in the selection.")
                self.notify("No text found", "The selection didn't contain readable text.", kind="warn")
                return
            self._record("text", title=util.shorten(text, 60), text=text, image=image,
                         extra={"engine": res.engine, "language": res.language})

        self._run_ocr(image, win, text_ready)

    def _action_translate(self, image: QImage) -> None:
        win = ResultWindow(self, image, kind="translate")
        self._track(win)
        win.set_busy("Reading text…")
        win.show()

        def text_ready(res) -> None:
            text = (res.text or "").strip()
            if not text:
                win.set_error("No text found in the selection.")
                return
            self.translate_into(win, text, record=True)

        self._run_ocr(image, win, text_ready)

    def translate_into(self, win: ResultWindow, text: str, target: str | None = None, source: str = "auto", user_picked: bool = False, record: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        if target in (None, "", "auto"):
            target = self.settings.resolved_target(text)
        win.set_translation_busy(target)
        s = self.settings

        def ok(out) -> None:
            win.set_translation(out)
            if record:
                self._record(
                    "translate",
                    title=util.shorten(text, 60),
                    text=text,
                    image=win.image,
                    extra={"translation": out.text, "detected": out.detected, "engine": out.engine, "target": out.target},
                )

        util.run_bg(
            lambda: translate_text(text, target, source=source, prefer=s.translate_engine),
            on_ok=ok,
            on_err=lambda k, m, tb: win.set_error(f"Translation failed: {m}"),
            name="translate",
        )

    def translate_text_window(self, text: str, image: QImage | None = None) -> None:
        if not (text or "").strip():
            return
        img = image if image is not None else QImage(2, 2, QImage.Format.Format_RGB32)
        win = ResultWindow(self, img, kind="translate", title=util.shorten(text, 60))
        self._track(win)
        win.set_text(text)
        win.show()
        self.translate_into(win, text, record=True)

    def _action_visual(self, image: QImage) -> None:
        engine = self.settings.visual_engine
        label = visual.ENGINE_LABELS.get(engine, engine)
        self.notify("Visual search", f"Uploading to {label}…", timeout=1500)
        data = png_bytes(image)

        def ok(url: str) -> None:
            util.open_url(url)
            self.notify(f"Opened {label}", "Visual matches opened in your browser.", kind="success",
                        action_label="Open again", action_cb=lambda: util.open_url(url))
            self._record("search", title=f"Visual search ({label})", text="", image=image,
                         extra={"url": url, "engine": engine})

        util.run_bg(
            lambda: visual.visual_search_url(data, engine),
            on_ok=ok,
            on_err=lambda k, m, tb: self.notify("Visual search failed", m, kind="error", timeout=6000),
            name="visual",
        )

    def _action_qr(self, image: QImage) -> None:
        from .qrscan import decode_codes

        def ok(codes: list) -> None:
            win = ResultWindow(self, image, kind="code")
            self._track(win)
            win.set_codes(codes)
            win.show()
            if codes:
                self._record("qr", title=codes[0].get("text", "")[:60], text=codes[0].get("text", ""),
                             image=image, extra={"codes": codes})
            else:
                self.notify("No code found", "No QR code or barcode in the selection.", kind="warn")

        util.run_bg(lambda: decode_codes(image), on_ok=ok,
                    on_err=lambda k, m, tb: self.notify("Scan failed", m, kind="error"), name="qr")

    # ---------------------------------------------------------------- song id
    def identify_song(self, seconds: int | None = None) -> None:
        if self._pill is not None:
            return
        s = self.settings
        secs = int(seconds or s.record_seconds)
        source = s.audio_source
        pill = ListeningPill(secs, source_label="System audio" if source == "system" else "Microphone")
        self._pill = pill
        pill.show_pill()

        def job():
            path = record_wav(
                seconds=secs,
                source=source,
                device_name=s.mic_device_name,
                progress=lambda frac: pill.progress.emit(frac),
                cancel=lambda: not pill.isVisible(),
            )
            pill.phase.emit("identifying")
            song = identify_song(path)
            return path, song

        def ok(result) -> None:
            path, song = result
            pill.close()
            self._pill = None
            win = SongWindow(self, song, path)
            self._song_windows.append(win)
            win.show()
            if song:
                self._record("audio", title=song.title, text=f"{song.artist} — {song.title}" if song.artist else song.title,
                             image=None,
                             extra={"artist": song.artist, "song_title": song.title, "youtube": song.youtube_url, "shazam": song.shazam_url})

        def err(kind: str, msg: str, tb: str) -> None:
            pill.close()
            self._pill = None
            if kind == "CaptureCancelled" or "cancel" in msg.lower():
                return
            SongWindow(self, None, "", error=msg).show()

        util.run_bg(job, on_ok=ok, on_err=err, name="songid")

    # ---------------------------------------------------------------- windows
    def _track(self, win) -> None:
        self.windows.append(win)
        win.destroyed.connect(lambda *_: self.windows.remove(win) if win in self.windows else None)

    def show_history(self) -> None:
        if self.history_window is None:
            self.history_window = HistoryWindow(self, self.history)
            self.history_window.destroyed.connect(lambda *_: setattr(self, "history_window", None))
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

    def show_home(self) -> None:
        if self.home_window is None:
            self.home_window = HomeWindow(self)
            self.home_window.destroyed.connect(lambda *_: setattr(self, "home_window", None))
        self.home_window.show()
        self.home_window.raise_()
        self.home_window.activateWindow()
        self.home_window.refresh_status()

    # ---------------------------------------------------------------- updates
    def _set_home_update_status(self, text: str) -> None:
        if self.home_window is not None:
            try:
                self.home_window.set_update_status(text)
            except RuntimeError:
                pass

    def check_for_updates(self, interactive: bool = True) -> None:
        repo = (self.settings.update_repo or update.DEFAULT_REPO).strip()
        cur = update.current_version()
        if interactive:
            self.notify("Checking for updates…", f"GitHub: {repo}", timeout=2000)

        def ok(info) -> None:
            if info is None:
                msg = f"v{cur} is the latest version."
                self._set_home_update_status(f"Updates: {msg}")
                if interactive:
                    self.notify("You're up to date", f"{__app_name__} {msg}", kind="success", timeout=4000)
                return
            self._set_home_update_status(f"Updates: v{info.version} available (you have v{cur})")
            if interactive:
                self._show_update_dialog(info, cur)
            else:
                self.notify(
                    f"Update available: v{info.version}",
                    f"You have v{cur} — click for details.",
                    kind="info",
                    timeout=9000,
                    action_label="Details",
                    action_cb=lambda: self._show_update_dialog(info, cur),
                )

        def err(kind: str, msg: str, tb: str) -> None:
            self._set_home_update_status(f"Updates: check failed ({msg})")
            if interactive:
                self.notify("Update check failed", msg, kind="warn", timeout=6000)

        util.run_bg(lambda: update.check_for_update(repo, current=cur), ok, err, name="update-check")

    def show_update_dialog(self, info: update.UpdateInfo) -> None:
        """Public entry for other windows (e.g. Options → Check now)."""
        self._show_update_dialog(info, update.current_version())

    def _show_update_dialog(self, info: update.UpdateInfo, cur: str) -> None:
        if self.update_dialog is not None:
            try:
                self.update_dialog.close()
            except RuntimeError:
                pass
        self.update_dialog = UpdateDialog(self, info, cur)
        self.update_dialog.finished.connect(lambda *_: setattr(self, "update_dialog", None))
        self.update_dialog.show()

    def download_update(self, info: update.UpdateInfo, dialog) -> None:
        asset = info.installer_asset()
        if asset is None:
            dialog.download_failed("no installer asset in this release")
            return
        if update.is_installed():
            dest = Path(tempfile.gettempdir()) / f"Glimpse-{info.version}-Setup.exe"
        else:
            dest = update.download_dir() / (asset.name or f"Glimpse-{info.version}-Setup.exe")

        def job():
            return update.download(asset.url, dest, progress=lambda done, total: dialog.progress_sig.emit(done, total))

        util.run_bg(
            job,
            on_ok=lambda path: dialog.download_finished(str(path)),
            on_err=lambda k, m, tb: dialog.download_failed(m),
            name="update-download",
        )

    def finish_update(self, path: str, dialog) -> None:
        if update.is_installed():
            if update.launch_installer(Path(path), silent=True, launch_after=True):
                dialog.accept()
                self.notify("Installing update", "Glimpse will close, update in place and restart.", timeout=3000)
                QTimer.singleShot(1500, self.quit)
            else:
                dialog.download_failed("could not start the installer")
        else:
            folder = str(Path(path).parent)
            util.open_path(folder)
            dialog.accept()
            self.notify(
                "Update downloaded",
                f"{Path(path).name} is in {folder} — this is the portable copy, so run the installer when you're ready.",
                kind="success", timeout=9000,
                action_label="Open folder", action_cb=lambda: util.open_path(folder),
            )

    def show_settings(self) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self, self.settings)
            self.settings_window.destroyed.connect(lambda *_: setattr(self, "settings_window", None))
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox()
        box.setWindowTitle(f"About {__app_name__}")
        box.setWindowIcon(icons.app_icon())
        box.setText(f"<b>{__app_name__} {__version__}</b><br>Google Lens for Windows.")
        hot = self.settings.hotkeys
        box.setInformativeText(
            "Snip any area of the screen, then read, translate, search, or scan it.<br><br>"
            f"<b>{hot.get('capture', '')}</b> — capture<br>"
            f"<b>{hot.get('translate', '')}</b> — capture &amp; translate<br>"
            f"<b>{hot.get('visual', '')}</b> — capture &amp; visual search<br>"
            f"<b>{hot.get('songid', '')}</b> — identify a song<br><br>"
            f"Data folder: {app_dir()}"
        )
        box.exec()

    # ---------------------------------------------------------------- services used by windows
    def notify(self, title: str, body: str = "", kind: str = "info", timeout: int = 3200, action_label: str | None = None, action_cb=None) -> None:
        if not self.settings.show_toasts and kind == "info":
            return
        self.toasts.show(title, body, kind=kind, timeout=timeout, action_label=action_label, action_cb=action_cb)

    def copy_text(self, text: str) -> None:
        util.copy_text(text)
        self.notify("Copied", util.shorten(text, 60), kind="success", timeout=2000)

    def open_url(self, url: str) -> None:
        if url:
            util.open_url(url)

    def save_image_dialog(self, image: QImage, parent=None) -> None:
        import time

        path, _ = QFileDialog.getSaveFileName(
            parent, "Save image", str(app_dir() / f"capture_{time.strftime('%Y%m%d_%H%M%S')}.png"), "PNG image (*.png)"
        )
        if path:
            image.save(path, "PNG")
            self.notify("Saved", path, kind="success")

    def fetch_cover_into(self, win, url: str) -> None:
        util.run_bg(lambda: fetch_cover(url), on_ok=lambda data: self._apply_cover(win, data), name="cover")

    def _apply_cover(self, win, data: bytes) -> None:
        try:
            win.set_cover(data)
        except RuntimeError:
            pass  # window closed

    def _record(self, kind: str, title: str = "", text: str = "", image=None, extra: dict | None = None) -> None:
        if not self.settings.save_history:
            return
        try:
            self.history.add(kind, title=title, text=text, extra=extra or {}, image=image)
        except Exception as e:  # noqa: BLE001
            log.warning("history save failed: %s", e)

    # ---------------------------------------------------------------- settings
    def apply_settings(self, new: Settings) -> None:
        self.settings = new
        new.save()
        errors = self.hotkeys.set_hotkeys(new.hotkeys)
        for action, err in errors.items():
            self.notify("Hotkey problem", err, kind="warn", timeout=6000)
        if autostart.supported():
            if not autostart.set_enabled(bool(new.autostart)):
                self.notify("Autostart", "Could not update the Windows startup entry.", kind="warn")
        self.history.limit = new.history_limit
        self.tray.setToolTip(f"{__app_name__} — capture: {new.hotkeys.get('capture', '')}")
        self._sync_autostart_menu()
        if self.home_window is not None:
            self.home_window.refresh_status()
        self.notify("Settings saved", "", kind="success", timeout=2000)

    # ---------------------------------------------------------------- lifecycle
    def _welcome(self) -> None:
        hot = self.settings.hotkeys
        self.notify(
            f"{__app_name__} is running",
            f"{hot.get('capture', '')} to capture • {hot.get('songid', '')} to identify a song",
            timeout=6000,
        )
        if not self.settings.first_run_done:
            self.settings.first_run_done = True
            try:
                self.settings.save()
            except Exception:
                pass
            QTimer.singleShot(1200, self.show_settings)

    def quit(self) -> None:
        log.info("quitting")
        self.hotkeys.unregister_all()
        self.tray.hide()
        self.qapp.quit()


def main(argv: list[str] | None = None) -> int:
    from . import cli

    args = cli.parse_args(list(sys.argv[1:] if argv is None else argv))
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    if cli.wants_cli(args):
        return cli.run(args)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    app.setOrganizationName(__app_name__)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icons.app_icon())
    theme_mod.apply(app)

    settings = Settings.load()
    single = SingleInstance()
    if not single.try_primary():
        from .single_instance import notify_primary

        notify_primary("show")
        log.info("another instance is already running; exiting")
        return 0

    controller = GlimpseApp(app, settings, single=single, start_hidden=bool(getattr(args, "tray", False)))
    if getattr(args, "exit_after", 0):
        QTimer.singleShot(int(args.exit_after * 1000), controller.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
