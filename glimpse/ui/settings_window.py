"""Settings window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .. import autostart, icons, util
from ..config import LANGUAGES, Settings, parse_hotkey
from ..ocr import available_languages
from ..paths import app_dir
from . import theme as T

ACTION_LABELS = {
    "capture": "Capture area",
    "translate": "Capture & translate",
    "visual": "Capture & visual search",
    "songid": "Identify song",
}

DEFAULT_ACTIONS = [
    ("text", "Read text (OCR)"),
    ("translate", "Translate"),
    ("visual", "Visual search"),
    ("qr", "Scan code / QR"),
    ("copy", "Copy image only"),
]


class SettingsWindow(QDialog):
    def __init__(self, controller, settings: Settings):
        super().__init__(None)
        self.controller = controller
        self.settings = settings
        self.setWindowTitle("Glimpse — Settings")
        self.setWindowIcon(icons.app_icon())
        self.resize(620, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("h1")
        root.addWidget(title)

        # -------------------------------------------------- hotkeys
        hk_group = QGroupBox("Hotkeys")
        hk_form = QFormLayout(hk_group)
        self.hk_edits: dict[str, QKeySequenceEdit] = {}
        for action, label in ACTION_LABELS.items():
            edit = QKeySequenceEdit(QKeySequence(settings.hotkeys.get(action, "")))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            self.hk_edits[action] = edit
            hk_form.addRow(label, edit)
        hk_hint = QLabel("Format: Ctrl+Alt+L — click a field, press the combination, then Save.")
        hk_hint.setObjectName("muted")
        hk_form.addRow("", hk_hint)
        self.hk_error = QLabel("")
        self.hk_error.setStyleSheet(f"color: {T.DANGER};")
        self.hk_error.setWordWrap(True)
        hk_form.addRow("", self.hk_error)
        root.addWidget(hk_group)

        # -------------------------------------------------- behaviour
        beh = QGroupBox("Capture behaviour")
        beh_form = QFormLayout(beh)
        self.default_action = QComboBox()
        for code, label in DEFAULT_ACTIONS:
            self.default_action.addItem(label, code)
        idx = self.default_action.findData(settings.default_action)
        self.default_action.setCurrentIndex(max(0, idx))
        beh_form.addRow("Double-click / Enter action", self.default_action)
        self.copy_on_capture = QCheckBox("Copy image to clipboard on every capture")
        self.copy_on_capture.setChecked(settings.copy_image_on_capture)
        beh_form.addRow("", self.copy_on_capture)
        self.save_history = QCheckBox("Save captures to history")
        self.save_history.setChecked(settings.save_history)
        beh_form.addRow("", self.save_history)
        self.history_limit = QSpinBox()
        self.history_limit.setRange(20, 5000)
        self.history_limit.setValue(int(settings.history_limit))
        beh_form.addRow("History limit", self.history_limit)
        root.addWidget(beh)

        # -------------------------------------------------- translation
        tr = QGroupBox("Translation")
        tr_form = QFormLayout(tr)
        self.target_lang = QComboBox()
        self.target_lang.addItem("Auto — swap with partner language", "auto")
        for code, name in LANGUAGES.items():
            if code == "auto":
                continue
            self.target_lang.addItem(name, code)
        idx = self.target_lang.findData(settings.target_lang)
        self.target_lang.setCurrentIndex(max(0, idx))
        tr_form.addRow("Translate to", self.target_lang)
        self.partner_lang = QComboBox()
        for code, name in LANGUAGES.items():
            if code == "auto":
                continue
            self.partner_lang.addItem(name, code)
        idx = self.partner_lang.findData(settings.secondary_lang)
        self.partner_lang.setCurrentIndex(max(0, idx))
        tr_form.addRow("Partner language (used by Auto)", self.partner_lang)
        self.translate_engine = QComboBox()
        self.translate_engine.addItem("Auto (try engines in order)", "auto")
        self.translate_engine.addItem("Google (clients5)", "google")
        self.translate_engine.addItem("MyMemory", "mymemory")
        idx = self.translate_engine.findData(settings.translate_engine)
        self.translate_engine.setCurrentIndex(max(0, idx))
        tr_form.addRow("Engine preference", self.translate_engine)
        root.addWidget(tr)

        # -------------------------------------------------- OCR
        ocr = QGroupBox("Text recognition (OCR)")
        ocr_form = QFormLayout(ocr)
        self.ocr_engine = QComboBox()
        self.ocr_engine.addItem("Windows OCR (built-in)", "windows")
        try:
            from ..ocr.tesseract_ocr import find_tesseract

            tess = find_tesseract()
        except Exception:
            tess = None
        self.ocr_engine.addItem("Tesseract" + ("" if tess else " (not installed)"), "tesseract")
        idx = self.ocr_engine.findData(settings.ocr_engine)
        self.ocr_engine.setCurrentIndex(max(0, idx))
        ocr_form.addRow("Engine", self.ocr_engine)
        self.ocr_language = QComboBox()
        self.ocr_language.addItem("Auto (user profile)", "")
        for lang in available_languages():
            self.ocr_language.addItem(lang, lang)
        idx = self.ocr_language.findData(settings.ocr_language)
        self.ocr_language.setCurrentIndex(max(0, idx))
        ocr_form.addRow("Language", self.ocr_language)
        ocr_hint = QLabel("More OCR languages come from Windows: Settings → Time & language → Language & region.")
        ocr_hint.setObjectName("muted")
        ocr_hint.setWordWrap(True)
        ocr_form.addRow("", ocr_hint)
        root.addWidget(ocr)

        # -------------------------------------------------- visual
        vis = QGroupBox("Visual search")
        vis_form = QFormLayout(vis)
        self.visual_engine = QComboBox()
        self.visual_engine.addItem("Google Lens", "google")
        self.visual_engine.addItem("Yandex Images (fallback: Google)", "yandex")
        idx = self.visual_engine.findData(settings.visual_engine)
        self.visual_engine.setCurrentIndex(max(0, idx))
        vis_form.addRow("Engine", self.visual_engine)
        root.addWidget(vis)

        # -------------------------------------------------- audio
        aud = QGroupBox("Song identification")
        aud_form = QFormLayout(aud)
        self.audio_source = QComboBox()
        self.audio_source.addItem("System audio (what's playing)", "system")
        self.audio_source.addItem("Microphone", "mic")
        idx = self.audio_source.findData(settings.audio_source)
        self.audio_source.setCurrentIndex(max(0, idx))
        self.audio_source.currentIndexChanged.connect(lambda _i: self._reload_devices())
        aud_form.addRow("Listen to", self.audio_source)
        self.audio_device = QComboBox()
        aud_form.addRow("Device (optional)", self.audio_device)
        self.record_seconds = QSpinBox()
        self.record_seconds.setRange(5, 20)
        self.record_seconds.setSuffix(" s")
        self.record_seconds.setValue(int(settings.record_seconds))
        aud_form.addRow("Listen duration", self.record_seconds)
        arow = QHBoxLayout()
        test_btn = QPushButton("Test listen")
        test_btn.setToolTip("Record a few seconds to verify the device works")
        test_btn.clicked.connect(self._test_listen)
        arow.addWidget(test_btn)
        arow.addStretch(1)
        aud_form.addRow("", arow)
        root.addWidget(aud)

        # -------------------------------------------------- app
        app_group = QGroupBox("Application")
        app_form = QFormLayout(app_group)
        self.autostart_box = QCheckBox("Start Glimpse with Windows (tray)")
        self.autostart_box.setChecked(autostart.is_enabled() if autostart.supported() else settings.autostart)
        if not autostart.supported():
            self.autostart_box.setEnabled(False)
            self.autostart_box.setToolTip("Available in the installed build")
        app_form.addRow("", self.autostart_box)
        self.show_toasts = QCheckBox("Show toast notifications")
        self.show_toasts.setChecked(settings.show_toasts)
        app_form.addRow("", self.show_toasts)
        brows = QHBoxLayout()
        data_btn = QPushButton("Open data folder")
        data_btn.clicked.connect(lambda: util.open_path(str(app_dir())))
        log_btn = QPushButton("Open log")
        log_btn.clicked.connect(lambda: util.open_path(str(app_dir() / "glimpse.log")))
        brows.addWidget(data_btn)
        brows.addWidget(log_btn)
        brows.addStretch(1)
        app_form.addRow("", brows)
        root.addWidget(app_group)

        # -------------------------------------------------- updates
        upd = QGroupBox("Updates")
        upd_form = QFormLayout(upd)
        self.check_updates = QCheckBox("Check for updates when Glimpse starts")
        self.check_updates.setChecked(settings.check_updates_on_start)
        upd_form.addRow("", self.check_updates)
        self.update_repo = QLineEdit(settings.update_repo)
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
        root.addWidget(upd)

        root.addStretch(1)

        # -------------------------------------------------- footer
        footer = QHBoxLayout()
        restore = QPushButton("Restore defaults")
        restore.clicked.connect(self._restore_defaults)
        footer.addWidget(restore)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        footer.addWidget(save)
        root.addLayout(footer)

        self._reload_devices()
        self._placed = False

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
        idx = self.visual_engine.findData(defaults.visual_engine)
        self.visual_engine.setCurrentIndex(max(0, idx))
        idx = self.audio_source.findData(defaults.audio_source)
        self.audio_source.setCurrentIndex(max(0, idx))
        self.record_seconds.setValue(defaults.record_seconds)
        self.show_toasts.setChecked(defaults.show_toasts)
        self.check_updates.setChecked(defaults.check_updates_on_start)
        self.update_repo.setText(defaults.update_repo)

    # ---------------------------------------------------------------- save
    def _collect(self) -> Settings | None:
        hotkeys = {}
        bad = []
        for action, edit in self.hk_edits.items():
            spec = edit.keySequence().toString(QKeySequence.SequenceFormat.NativeText)
            hotkeys[action] = spec
            if spec and parse_hotkey(spec) is None:
                bad.append(f"{ACTION_LABELS[action]}: '{spec}' cannot be used (need modifiers like Ctrl/Alt + a key)")
        if bad:
            self.hk_error.setText("\n".join(bad))
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
        s.visual_engine = self.visual_engine.currentData()
        s.audio_source = self.audio_source.currentData()
        s.mic_device_name = self.audio_device.currentData() or ""
        s.record_seconds = self.record_seconds.value()
        s.autostart = self.autostart_box.isChecked()
        s.show_toasts = self.show_toasts.isChecked()
        s.check_updates_on_start = self.check_updates.isChecked()
        s.update_repo = self.update_repo.text().strip() or "Zcc09/Glimpse"
        s.first_run_done = self.settings.first_run_done
        return s

    def _save(self) -> None:
        new = self._collect()
        if new is None:
            return
        if self.controller:
            self.controller.apply_settings(new)
        self.accept()

    # ---------------------------------------------------------------- lifecycle
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if not self._placed:
            self._placed = True
            screen = QGuiApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                self.move(
                    avail.left() + max(12, (avail.width() - self.width()) // 2),
                    avail.top() + max(12, (avail.height() - self.height()) // 5),
                )
