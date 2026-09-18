"""Settings window: tabbed and resizable, one tab per settings group."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import autostart, icons, util
from ..config import LANGUAGES, Settings, parse_hotkey
from ..ocr import available_languages, tesseract_available
from ..paths import app_dir
from . import theme as T

ACTION_LABELS = {
    "capture": "Capture area",
    "translate": "Capture & translate",
    "visual": "Capture & visual search",
    "songid": "Identify song",
    "record": "Record region (starts/stops)",
}

DEFAULT_ACTIONS = [
    ("text", "Read text (OCR)"),
    ("translate", "Translate"),
    ("visual", "Visual search"),
    ("qr", "Scan code / QR"),
    ("save", "Save screenshot"),
    ("copy", "Copy image only"),
]

TAB_GENERAL, TAB_HOTKEYS, TAB_TEXT = 0, 1, 2


def _scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidget(inner)
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return sa


class _Downloader(QObject):
    """Downloads Tesseract language files on a worker thread, reporting progress."""

    progress = Signal(str, int, int)  # code, done, total
    finished = Signal(list, list)  # ok codes, [(code, error), …]

    def __init__(self, codes: list[str]):
        super().__init__()
        self.codes = list(codes)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="glimpse-tess-dl").start()

    def _run(self) -> None:
        from ..ocr import languages as L

        ok: list[str] = []
        bad: list[tuple[str, str]] = []
        for code in self.codes:
            try:
                L.download_language(code, progress=lambda d, t, c=code: self.progress.emit(c, d, t))
                ok.append(code)
            except Exception as e:  # noqa: BLE001
                bad.append((code, str(e)))
        self.finished.emit(ok, bad)


class SettingsWindow(QDialog):
    def __init__(self, controller, settings: Settings):
        super().__init__(None)
        self.controller = controller
        self.settings = settings
        self.setWindowTitle("Glimpse — Settings")
        self.setWindowIcon(icons.app_icon())

        size = list(getattr(settings, "ui_settings_size", []) or [])
        self.resize(*(size if len(size) == 2 else [960, 680]))
        self.setMinimumSize(820, 560)
        self._placed = False
        self._dl: _Downloader | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QVBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("h1")
        head.addWidget(title)
        sub = QLabel("Glimpse — snip the screen, read it, translate it, search it.")
        sub.setObjectName("muted")
        head.addWidget(sub)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.addTab(_scroll(self._tab_general()), "General")
        self.tabs.addTab(_scroll(self._tab_hotkeys()), "Hotkeys")
        self.tabs.addTab(_scroll(self._tab_text()), "Text (OCR)")
        self.tabs.addTab(_scroll(self._tab_translation()), "Translation")
        self.tabs.addTab(_scroll(self._tab_visual()), "Visual search")
        self.tabs.addTab(_scroll(self._tab_audio()), "Audio")
        self.tabs.addTab(_scroll(self._tab_updates()), "Updates")
        self.tabs.addTab(_scroll(self._tab_app()), "App")
        idx = int(getattr(settings, "ui_settings_tab", 0) or 0)
        self.tabs.setCurrentIndex(min(max(0, idx), self.tabs.count() - 1))
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        restore = QPushButton("Restore defaults")
        restore.clicked.connect(self._restore_defaults)
        footer.addWidget(restore)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(lambda: self._save(close=False))
        footer.addWidget(apply_btn)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(lambda: self._save(close=True))
        footer.addWidget(save)
        root.addLayout(footer)

        self._reload_devices()

    # ---------------------------------------------------------------- tabs
    def _tab_general(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        beh = QGroupBox("Capture")
        beh_form = QFormLayout(beh)
        self.default_action = QComboBox()
        for code, label in DEFAULT_ACTIONS:
            self.default_action.addItem(label, code)
        idx = self.default_action.findData(self.settings.default_action)
        self.default_action.setCurrentIndex(max(0, idx))
        beh_form.addRow("Double-click / Enter action", self.default_action)
        self.copy_on_capture = QCheckBox("Copy image to clipboard on every capture")
        self.copy_on_capture.setChecked(self.settings.copy_image_on_capture)
        beh_form.addRow("", self.copy_on_capture)
        self.save_history = QCheckBox("Save captures to history")
        self.save_history.setChecked(self.settings.save_history)
        beh_form.addRow("", self.save_history)
        self.history_limit = QSpinBox()
        self.history_limit.setRange(20, 5000)
        self.history_limit.setValue(int(self.settings.history_limit))
        beh_form.addRow("History limit", self.history_limit)
        lay.addWidget(beh)

        notify = QGroupBox("Notifications")
        notify_form = QFormLayout(notify)
        self.show_toasts = QCheckBox("Show toast notifications")
        self.show_toasts.setChecked(self.settings.show_toasts)
        notify_form.addRow("", self.show_toasts)
        lay.addWidget(notify)

        start = QGroupBox("Startup")
        start_form = QFormLayout(start)
        self.autostart_box = QCheckBox("Start Glimpse with Windows (tray)")
        self.autostart_box.setChecked(
            autostart.is_enabled() if autostart.supported() else self.settings.autostart
        )
        if not autostart.supported():
            self.autostart_box.setEnabled(False)
            self.autostart_box.setToolTip("Available in the installed build")
        start_form.addRow("", self.autostart_box)
        lay.addWidget(start)

        media = QGroupBox("Screenshots & recordings")
        media_form = QFormLayout(media)
        from ..paths import known_folder

        shots_default = str(known_folder("Pictures") / "Glimpse")
        clips_default = str(known_folder("Videos") / "Glimpse")
        self.screens_dir = QLineEdit(self.settings.screenshot_dir or "")
        self.screens_dir.setPlaceholderText(shots_default)
        shots_row = QHBoxLayout()
        shots_row.addWidget(self.screens_dir, 1)
        shots_browse = QPushButton("Browse…")
        shots_browse.clicked.connect(lambda: self._pick_dir(self.screens_dir, shots_default))
        shots_row.addWidget(shots_browse)
        media_form.addRow("Screenshots folder", shots_row)

        self.clips_dir_edit = QLineEdit(self.settings.record_dir or "")
        self.clips_dir_edit.setPlaceholderText(clips_default)
        clips_row = QHBoxLayout()
        clips_row.addWidget(self.clips_dir_edit, 1)
        clips_browse = QPushButton("Browse…")
        clips_browse.clicked.connect(lambda: self._pick_dir(self.clips_dir_edit, clips_default))
        clips_row.addWidget(clips_browse)
        media_form.addRow("Recordings folder", clips_row)

        self.record_fps_spin = QSpinBox()
        self.record_fps_spin.setRange(5, 30)
        self.record_fps_spin.setSuffix(" fps")
        self.record_fps_spin.setValue(int(getattr(self.settings, "record_fps", 15)))
        media_form.addRow("Recording frame rate", self.record_fps_spin)

        self.record_max_spin = QSpinBox()
        self.record_max_spin.setRange(5, 3600)
        self.record_max_spin.setSuffix(" s")
        self.record_max_spin.setValue(int(getattr(self.settings, "record_max_seconds", 300)))
        media_form.addRow("Recording limit", self.record_max_spin)

        self.record_audio_box = QCheckBox("Record system audio with the video (muxed with ffmpeg)")
        self.record_audio_box.setChecked(bool(getattr(self.settings, "record_audio", False)))
        media_form.addRow("", self.record_audio_box)

        from ..record import ffmpeg_available

        ff = QLabel(
            "ffmpeg: found — recordings work."
            if ffmpeg_available()
            else "ffmpeg: not found — recording needs it (winget install Gyan.FFmpeg)."
        )
        ff.setObjectName("muted")
        ff.setWordWrap(True)
        media_form.addRow("", ff)
        lay.addWidget(media)
        lay.addStretch(1)
        return w

    def _pick_dir(self, field: QLineEdit, fallback: str) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = field.text().strip() or fallback
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if chosen:
            field.setText(chosen)

    def _tab_hotkeys(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        hk_group = QGroupBox("Global hotkeys")
        hk_form = QFormLayout(hk_group)
        self.hk_edits: dict[str, QKeySequenceEdit] = {}
        for action, label in ACTION_LABELS.items():
            edit = QKeySequenceEdit(QKeySequence(self.settings.hotkeys.get(action, "")))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            self.hk_edits[action] = edit
            hk_form.addRow(label, edit)
        hint = QLabel("Format: Ctrl+Alt+L — click a field, press the combination, then Save.")
        hint.setObjectName("muted")
        hk_form.addRow("", hint)
        self.hk_error = QLabel("")
        self.hk_error.setStyleSheet(f"color: {T.DANGER};")
        self.hk_error.setWordWrap(True)
        hk_form.addRow("", self.hk_error)
        lay.addWidget(hk_group)

        live = QGroupBox("Current registration")
        live_lay = QVBoxLayout(live)
        registered = getattr(self.controller, "registered_hotkeys", None)
        self.hotkey_status = QLabel("")
        self.hotkey_status.setObjectName("muted")
        self.hotkey_status.setWordWrap(True)
        if isinstance(registered, dict) and registered:
            self.hotkey_status.setText(
                "\n".join(f"{ACTION_LABELS.get(a, a)} → {spec}" for a, spec in registered.items())
            )
        else:
            self.hotkey_status.setText("Registered while Glimpse is running.")
        live_lay.addWidget(self.hotkey_status)
        lay.addWidget(live)
        lay.addStretch(1)
        return w

    def _tab_text(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        eng = QGroupBox("Engine")
        eng_form = QFormLayout(eng)
        self.ocr_engine = QComboBox()
        self.ocr_engine.addItem("Auto — Windows OCR, Tesseract as safety net", "auto")
        self.ocr_engine.addItem("Windows OCR (built-in, fastest)", "windows")
        tess = tesseract_available()
        self.ocr_engine.addItem("Tesseract" + ("" if tess else " (not available)"), "tesseract")
        idx = self.ocr_engine.findData(self.settings.ocr_engine)
        self.ocr_engine.setCurrentIndex(max(0, idx))
        eng_form.addRow("Text recognition", self.ocr_engine)

        wins = available_languages()
        self.ocr_language = QComboBox()
        auto_label = "Auto — every installed language"
        if wins:
            auto_label += f" ({', '.join(wins[:6])}{'…' if len(wins) > 6 else ''})"
        self.ocr_language.addItem(auto_label, "")
        for lang in wins:
            self.ocr_language.addItem(lang, lang)
        idx = self.ocr_language.findData(self.settings.ocr_language)
        self.ocr_language.setCurrentIndex(max(0, idx))
        eng_form.addRow("Windows OCR language", self.ocr_language)
        win_hint = QLabel(
            f"Windows OCR sees {len(wins) or 'no'} language pack(s). More come from Windows "
            "itself — add a language under Language & region and tick "
            "“Optical character recognition”."
        )
        win_hint.setObjectName("muted")
        win_hint.setWordWrap(True)
        eng_form.addRow("", win_hint)
        win_row = QHBoxLayout()
        win_btn = QPushButton("Open Windows language settings")
        win_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("ms-settings:regionlanguage"))
        )
        win_row.addWidget(win_btn)
        win_row.addStretch(1)
        eng_form.addRow("", win_row)
        self.use_all_langs = QCheckBox(
            "Always try every installed language (recommended)"
        )
        self.use_all_langs.setChecked(bool(getattr(self.settings, "ocr_use_all_languages", True)))
        self.use_all_langs.setToolTip(
            "Snips in any script are read by the right model — not only by the languages ticked below."
        )
        eng_form.addRow("", self.use_all_langs)
        lay.addWidget(eng)

        # ---------------------------------------------------- tesseract languages
        tess_group = QGroupBox("Tesseract languages (any of 126, offline)")
        tf = QVBoxLayout(tess_group)
        state = (
            "bundled with Glimpse — nothing to install"
            if tess
            else "not found (no bundled engine and none on PATH)"
        )
        self.tess_status = QLabel(f"Engine: {state}")
        self.tess_status.setObjectName("muted")
        self.tess_status.setWordWrap(True)
        tf.addWidget(self.tess_status)

        row = QHBoxLayout()
        self.lang_filter = QLineEdit()
        self.lang_filter.setPlaceholderText("Filter languages…")
        self.lang_filter.textChanged.connect(self._filter_languages)
        row.addWidget(self.lang_filter, 1)
        sel_all = QPushButton("Select common")
        sel_all.setToolTip("Tick the ~30 languages most people need")
        sel_all.clicked.connect(self._tick_common)
        row.addWidget(sel_all)
        tf.addLayout(row)

        self.lang_tree = QTreeWidget()
        self.lang_tree.setColumnCount(2)
        self.lang_tree.setHeaderLabels(["Language", "Status"])
        self.lang_tree.setRootIsDecorated(False)
        self.lang_tree.setUniformRowHeights(True)
        self.lang_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.lang_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lang_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.lang_tree.setMinimumHeight(220)
        tf.addWidget(self.lang_tree, 1)

        self.lang_status = QLabel("")
        self.lang_status.setObjectName("muted")
        self.lang_status.setWordWrap(True)
        tf.addWidget(self.lang_status)

        self.lang_progress = QProgressBar()
        self.lang_progress.setVisible(False)
        tf.addWidget(self.lang_progress)

        btn_row = QHBoxLayout()
        self.dl_btn = QPushButton("Download ticked")
        self.dl_btn.setObjectName("primary")
        self.dl_btn.clicked.connect(self._download_checked)
        btn_row.addWidget(self.dl_btn)
        self.dl_all_btn = QPushButton("Download all common")
        self.dl_all_btn.clicked.connect(self._download_common)
        btn_row.addWidget(self.dl_all_btn)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._populate_languages)
        btn_row.addWidget(refresh)
        open_dir = QPushButton("Open data folder")
        open_dir.clicked.connect(lambda: util.open_path(str(app_dir() / "tessdata")))
        btn_row.addWidget(open_dir)
        btn_row.addStretch(1)
        tf.addLayout(btn_row)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test OCR")
        self.test_btn.setToolTip("Read a sample with the current engine and languages")
        self.test_btn.clicked.connect(self._test_ocr)
        test_row.addWidget(self.test_btn)
        self.test_out = QLabel("")
        self.test_out.setObjectName("muted")
        self.test_out.setWordWrap(True)
        test_row.addWidget(self.test_out, 1)
        tf.addLayout(test_row)
        lay.addWidget(tess_group, 1)

        self._populate_languages()
        return w

    def _tab_translation(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        tr = QGroupBox("Translation")
        tr_form = QFormLayout(tr)
        self.target_lang = QComboBox()
        self.target_lang.addItem("Auto — swap with partner language", "auto")
        for code, name in LANGUAGES.items():
            if code == "auto":
                continue
            self.target_lang.addItem(name, code)
        idx = self.target_lang.findData(self.settings.target_lang)
        self.target_lang.setCurrentIndex(max(0, idx))
        tr_form.addRow("Translate to", self.target_lang)
        self.partner_lang = QComboBox()
        for code, name in LANGUAGES.items():
            if code == "auto":
                continue
            self.partner_lang.addItem(name, code)
        idx = self.partner_lang.findData(self.settings.secondary_lang)
        self.partner_lang.setCurrentIndex(max(0, idx))
        tr_form.addRow("Partner language (used by Auto)", self.partner_lang)
        self.translate_engine = QComboBox()
        self.translate_engine.addItem("Auto (try engines in order)", "auto")
        self.translate_engine.addItem("Google", "google")
        self.translate_engine.addItem("MyMemory", "mymemory")
        idx = self.translate_engine.findData(self.settings.translate_engine)
        self.translate_engine.setCurrentIndex(max(0, idx))
        tr_form.addRow("Engine preference", self.translate_engine)
        hint = QLabel(
            "Auto translates into English when the text is in the partner language, and "
            "into the partner language otherwise."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        tr_form.addRow("", hint)
        lay.addWidget(tr)
        lay.addStretch(1)
        return w

    def _tab_visual(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        vis = QGroupBox("Visual search")
        vis_form = QFormLayout(vis)
        self.visual_engine = QComboBox()
        self.visual_engine.addItem("Google Lens", "google")
        self.visual_engine.addItem("Yandex Images (falls back to Google)", "yandex")
        idx = self.visual_engine.findData(self.settings.visual_engine)
        self.visual_engine.setCurrentIndex(max(0, idx))
        vis_form.addRow("Engine", self.visual_engine)
        vhint = QLabel("Results open in your browser with the whole image as the query.")
        vhint.setObjectName("muted")
        vhint.setWordWrap(True)
        vis_form.addRow("", vhint)
        lay.addWidget(vis)
        lay.addStretch(1)
        return w

    def _tab_audio(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        aud = QGroupBox("Song identification")
        aud_form = QFormLayout(aud)
        self.audio_source = QComboBox()
        self.audio_source.addItem("System audio (what's playing)", "system")
        self.audio_source.addItem("Microphone", "mic")
        idx = self.audio_source.findData(self.settings.audio_source)
        self.audio_source.setCurrentIndex(max(0, idx))
        self.audio_source.currentIndexChanged.connect(lambda _i: self._reload_devices())
        aud_form.addRow("Listen to", self.audio_source)
        self.audio_device = QComboBox()
        aud_form.addRow("Device (optional)", self.audio_device)
        self.record_seconds = QSpinBox()
        self.record_seconds.setRange(5, 20)
        self.record_seconds.setSuffix(" s")
        self.record_seconds.setValue(int(self.settings.record_seconds))
        aud_form.addRow("Listen duration", self.record_seconds)
        arow = QHBoxLayout()
        test_btn = QPushButton("Test listen")
        test_btn.setToolTip("Record a few seconds to verify the device works")
        test_btn.clicked.connect(self._test_listen)
        arow.addWidget(test_btn)
        arow.addStretch(1)
        aud_form.addRow("", arow)
        lay.addWidget(aud)
        lay.addStretch(1)
        return w

    def _tab_updates(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        upd = QGroupBox("Updates")
        upd_form = QFormLayout(upd)
        self.check_updates = QCheckBox("Check for updates when Glimpse starts")
        self.check_updates.setChecked(self.settings.check_updates_on_start)
        upd_form.addRow("", self.check_updates)
        self.update_repo = QLineEdit(self.settings.update_repo)
        self.update_repo.setPlaceholderText("owner/repo")
        self.update_repo.setToolTip("The public GitHub repository whose releases Glimpse checks")
        upd_form.addRow("GitHub repository", self.update_repo)
        upd_row = QHBoxLayout()
        check_now = QPushButton("Check now")
        check_now.clicked.connect(self._check_updates_now)
        upd_row.addWidget(check_now)
        self.update_result = QLabel("")
        self.update_result.setObjectName("muted")
        upd_row.addWidget(self.update_result, 1)
        upd_form.addRow("", upd_row)
        lay.addWidget(upd)
        lay.addStretch(1)
        return w

    def _tab_app(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        info = QGroupBox("Files and logs")
        info_form = QFormLayout(info)
        brows = QHBoxLayout()
        data_btn = QPushButton("Open data folder")
        data_btn.clicked.connect(lambda: util.open_path(str(app_dir())))
        log_btn = QPushButton("Open log")
        log_btn.clicked.connect(lambda: util.open_path(str(app_dir() / "glimpse.log")))
        brows.addWidget(data_btn)
        brows.addWidget(log_btn)
        brows.addStretch(1)
        info_form.addRow("", brows)
        from .. import __version__

        ver = QLabel(f"Glimpse v{__version__}")
        ver.setObjectName("muted")
        info_form.addRow("Version", ver)
        lay.addWidget(info)
        lay.addStretch(1)
        return w

    # ---------------------------------------------------------------- OCR languages
    def _populate_languages(self) -> None:
        from ..ocr import languages as L

        installed = set(L.installed_languages())
        # keep whatever the user has ticked right now (e.g. after a download)
        prev = self._checked_codes() if self._lang_items() else []
        wanted = set(prev) if prev else set(self.settings.tess_languages or [])
        self.lang_tree.clear()
        self._items: dict[str, QTreeWidgetItem] = {}
        for code in sorted(L.LANGUAGE_NAMES, key=lambda c: L.LANGUAGE_NAMES[c].lower()):
            is_in = code in installed
            item = QTreeWidgetItem(
                [f"{L.LANGUAGE_NAMES[code]} ({code})", "installed" if is_in else "not downloaded"]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, code)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0, Qt.CheckState.Checked if code in wanted else Qt.CheckState.Unchecked
            )
            if is_in:
                item.setForeground(1, QBrush(QColor(T.OK)))
            self.lang_tree.addTopLevelItem(item)
            self._items[code] = item
        self._update_lang_status()

    def _lang_items(self) -> dict[str, QTreeWidgetItem]:
        return getattr(self, "_items", {})

    def _checked_codes(self) -> list[str]:
        return [c for c, item in self._lang_items().items() if item.checkState(0) == Qt.CheckState.Checked]

    def _update_lang_status(self) -> None:
        from ..ocr import languages as L

        installed = sorted(L.installed_languages())
        missing = [c for c in self._checked_codes() if c not in set(installed)]
        msg = f"{len(installed)} language(s) on disk: {', '.join(installed[:14]) or '—'}"
        if missing:
            msg += f"\n{len(missing)} ticked but not downloaded: {', '.join(missing)}"
        self.lang_status.setText(msg)
        self.dl_btn.setEnabled(bool(missing) and self._dl is None)
        self.dl_all_btn.setEnabled(self._dl is None)

    def _filter_languages(self, needle: str) -> None:
        needle = needle.strip().lower()
        for code, item in self._lang_items().items():
            text = item.text(0).lower()
            item.setHidden(bool(needle) and needle not in text)

    def _tick_common(self) -> None:
        from ..ocr import languages as L

        common = set(L.COMMON)
        for code, item in self._lang_items().items():
            item.setCheckState(
                0, Qt.CheckState.Checked if code in common else Qt.CheckState.Unchecked
            )
        self._update_lang_status()

    def _download_checked(self) -> None:
        self._start_download([c for c in self._checked_codes()])

    def _download_common(self) -> None:
        from ..ocr import languages as L

        missing = [c for c in L.COMMON if c not in set(L.installed_languages())]
        if not missing:
            self.lang_status.setText("All common languages are already installed.")
            return
        answer = QMessageBox.question(
            self,
            "Download languages",
            f"Download {len(missing)} common language(s) (~60 MB) into the Glimpse data folder?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_download(missing)

    def _start_download(self, codes: list[str]) -> None:
        from ..ocr import languages as L

        codes = [c for c in codes if c not in set(L.installed_languages())]
        if not codes:
            self.lang_status.setText("Everything ticked is already downloaded.")
            return
        self._dl = _Downloader(codes)
        self._dl.progress.connect(self._on_dl_progress)
        self._dl.finished.connect(self._on_dl_finished)
        self.lang_progress.setRange(0, 0)
        self.lang_progress.setVisible(True)
        self.lang_status.setText(f"Downloading {len(codes)} language(s)…")
        self.test_btn.setEnabled(False)
        self._update_lang_status()
        self._dl.start()

    def _on_dl_progress(self, code: str, done: int, total: int) -> None:
        from ..ocr import languages as L

        name = L.LANGUAGE_NAMES.get(code, code)
        if total > 0:
            pct = int(done * 100 / total)
            self.lang_progress.setRange(0, 100)
            self.lang_progress.setValue(pct)
            self.lang_progress.setFormat(f"{name} {pct}%")
        else:
            self.lang_progress.setFormat(f"{name} {done // 1024} KB")

    def _on_dl_finished(self, ok: list[str], bad: list) -> None:
        self._dl = None
        self.lang_progress.setVisible(False)
        self.lang_progress.setRange(0, 100)
        self.lang_progress.setValue(0)
        self.test_btn.setEnabled(True)
        self._populate_languages()
        for code in ok:  # a freshly downloaded language starts ticked
            item = self._lang_items().get(code)
            if item is not None:
                item.setCheckState(0, Qt.CheckState.Checked)
        self._update_lang_status()
        parts = []
        if ok:
            parts.append(f"downloaded {len(ok)}: {', '.join(ok)}")
        if bad:
            parts.append("failed: " + ", ".join(f"{c} ({e})" for c, e in bad))
        self.lang_status.setText("; ".join(parts) or "nothing to do")

    def _test_ocr(self) -> None:
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter

        engine = self.ocr_engine.currentData()
        ticked = self._checked_codes()
        self.test_out.setText("reading a sample…")
        self.test_btn.setEnabled(False)

        def render(text: str, size: int, width: int, height: int) -> QImage:
            img = QImage(width, height, QImage.Format.Format_RGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            p.setPen(QColor("black"))
            f = QFont("Segoe UI")
            f.setPixelSize(size)
            p.setFont(f)
            p.drawText(0, 0, width, height, _Qt.AlignmentFlag.AlignCenter, text)
            p.end()
            return img

        samples = [("English", render("Glimpse settings 1234", 40, 700, 140))]
        if any(c in ticked for c in ("ara", "urd", "fas")):
            samples.append(
                ("Arabic", render("الطقس جميل اليوم. أريد أن أطلب قهوة من المقهى الجديد.", 34, 900, 160))
            )

        def work() -> list[str]:
            from ..ocr import recognize

            out = []
            for label, img in samples:
                try:
                    res = recognize(
                        img, language="", engine=engine, tess_languages=ticked,
                        all_languages=bool(self.use_all_langs.isChecked()),
                    )
                    flag = " ⚠ low confidence" if res.low_confidence else ""
                    conf = f" conf {res.confidence:.0f}%" if res.confidence else ""
                    out.append(f"{label} · {res.engine} ({res.language}){conf}{flag}: {res.text!r}")
                except Exception as e:  # noqa: BLE001
                    out.append(f"{label} · failed: {type(e).__name__}: {e}")
            return out

        def ok(lines: list) -> None:
            self.test_btn.setEnabled(True)
            self.test_out.setText("\n".join(lines))

        def err(kind: str, msg: str, tb: str) -> None:
            self.test_btn.setEnabled(True)
            self.test_out.setText(f"test failed: {msg}")

        util.run_bg(work, ok, err, name="ocr-test")

    # ---------------------------------------------------------------- helpers
    def _reload_devices(self) -> None:
        self.audio_device.clear()
        self.audio_device.addItem("Default", "")
        kind = self.audio_source.currentData()
        try:
            from ..audio import list_sources

            for src in list_sources():
                if src["kind"] != kind:
                    continue
                label = src["name"] + (" (default)" if src["default"] else "")
                self.audio_device.addItem(label, src["name"])
        except Exception:
            self.audio_device.addItem("(device list unavailable)", "")
        idx = self.audio_device.findData(self.settings.mic_device_name)
        if idx >= 0:
            self.audio_device.setCurrentIndex(idx)

    def _test_listen(self) -> None:
        if self.controller:
            self.controller.identify_song(seconds=4)

    def _check_updates_now(self) -> None:
        from .. import update
        from ..util import run_bg

        repo = self.update_repo.text().strip() or update.DEFAULT_REPO
        self.update_result.setText(f"checking {repo}…")

        def ok(info) -> None:
            if info is None:
                self.update_result.setText(f"up to date (v{update.current_version()})")
                return
            self.update_result.setText(f"v{info.version} available")
            if self.controller:
                self.controller.show_update_dialog(info)

        def err(kind: str, msg: str, tb: str) -> None:
            self.update_result.setText(f"check failed: {msg}")

        run_bg(lambda: update.check_for_update(repo), ok, err, name="update-check")

    def _restore_defaults(self) -> None:
        defaults = Settings()
        for action, edit in self.hk_edits.items():
            edit.setKeySequence(QKeySequence(defaults.hotkeys.get(action, "")))
        idx = self.default_action.findData(defaults.default_action)
        self.default_action.setCurrentIndex(max(0, idx))
        self.copy_on_capture.setChecked(defaults.copy_image_on_capture)
        self.save_history.setChecked(defaults.save_history)
        self.history_limit.setValue(defaults.history_limit)
        idx = self.target_lang.findData(defaults.target_lang)
        self.target_lang.setCurrentIndex(max(0, idx))
        idx = self.partner_lang.findData(defaults.secondary_lang)
        self.partner_lang.setCurrentIndex(max(0, idx))
        idx = self.translate_engine.findData(defaults.translate_engine)
        self.translate_engine.setCurrentIndex(max(0, idx))
        idx = self.ocr_engine.findData(defaults.ocr_engine)
        self.ocr_engine.setCurrentIndex(max(0, idx))
        self.ocr_language.setCurrentIndex(0)
        self.use_all_langs.setChecked(bool(defaults.ocr_use_all_languages))
        idx = self.visual_engine.findData(defaults.visual_engine)
        self.visual_engine.setCurrentIndex(max(0, idx))
        idx = self.audio_source.findData(defaults.audio_source)
        self.audio_source.setCurrentIndex(max(0, idx))
        self.record_seconds.setValue(defaults.record_seconds)
        self.show_toasts.setChecked(defaults.show_toasts)
        self.check_updates.setChecked(defaults.check_updates_on_start)
        self.update_repo.setText(defaults.update_repo)
        self.screens_dir.setText(defaults.screenshot_dir)
        self.clips_dir_edit.setText(defaults.record_dir)
        self.record_fps_spin.setValue(defaults.record_fps)
        self.record_max_spin.setValue(defaults.record_max_seconds)
        self.record_audio_box.setChecked(defaults.record_audio)
        wanted = set(defaults.tess_languages)
        for code, item in self._lang_items().items():
            item.setCheckState(0, Qt.CheckState.Checked if code in wanted else Qt.CheckState.Unchecked)
        self._update_lang_status()
        self.hk_error.setText("")

    # ---------------------------------------------------------------- save
    def _collect(self) -> Settings | None:
        hotkeys = {}
        bad = []
        for action, edit in self.hk_edits.items():
            spec = edit.keySequence().toString(QKeySequence.SequenceFormat.NativeText)
            hotkeys[action] = spec
            if spec and parse_hotkey(spec) is None:
                bad.append(
                    f"{ACTION_LABELS[action]}: '{spec}' cannot be used (need modifiers like Ctrl/Alt + a key)"
                )
        if bad:
            self.hk_error.setText("\n".join(bad))
            self.tabs.setCurrentIndex(TAB_HOTKEYS)
            return None
        self.hk_error.setText("")

        s = Settings()
        s.hotkeys = hotkeys
        s.default_action = self.default_action.currentData()
        s.copy_image_on_capture = self.copy_on_capture.isChecked()
        s.save_history = self.save_history.isChecked()
        s.history_limit = self.history_limit.value()
        s.target_lang = self.target_lang.currentData()
        s.secondary_lang = self.partner_lang.currentData()
        s.translate_engine = self.translate_engine.currentData()
        s.ocr_engine = self.ocr_engine.currentData()
        s.ocr_language = self.ocr_language.currentData() or ""
        s.tess_languages = self._checked_codes() or ["eng"]
        s.ocr_use_all_languages = bool(self.use_all_langs.isChecked())
        s.visual_engine = self.visual_engine.currentData()
        s.audio_source = self.audio_source.currentData()
        s.mic_device_name = self.audio_device.currentData() or ""
        s.record_seconds = self.record_seconds.value()
        s.autostart = self.autostart_box.isChecked()
        s.show_toasts = self.show_toasts.isChecked()
        s.check_updates_on_start = self.check_updates.isChecked()
        s.update_repo = self.update_repo.text().strip() or "Zcc09/Glimpse"
        s.screenshot_dir = self.screens_dir.text().strip()
        s.record_dir = self.clips_dir_edit.text().strip()
        s.record_fps = self.record_fps_spin.value()
        s.record_max_seconds = self.record_max_spin.value()
        s.record_audio = self.record_audio_box.isChecked()
        # carried over, not edited here
        s.first_run_done = self.settings.first_run_done
        s.ui_settings_size = list(getattr(self.settings, "ui_settings_size", []))
        s.ui_settings_tab = self.tabs.currentIndex()
        return s

    def _save(self, close: bool = True) -> None:
        new = self._collect()
        if new is None:
            return
        self.settings = new
        if self.controller:
            self.controller.apply_settings(new)
        if close:
            self.accept()

    def _persist_ui_state(self) -> None:
        """Remember the window size and open tab across runs."""
        try:
            self.settings.ui_settings_size = [self.width(), self.height()]
            self.settings.ui_settings_tab = self.tabs.currentIndex()
            self.settings.save()
        except Exception as e:  # noqa: BLE001
            from ..log import log

            log.warning("could not save settings window size: %s", e)

    # ---------------------------------------------------------------- lifecycle
    def done(self, code: int) -> None:  # noqa: D102
        self._persist_ui_state()
        super().done(code)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if not self._placed:
            self._placed = True
            screen = QGuiApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                self.move(
                    avail.left() + max(12, (avail.width() - self.width()) // 2),
                    avail.top() + max(12, (avail.height() - self.height()) // 6),
                )
