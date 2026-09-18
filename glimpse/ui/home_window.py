"""The window the tray's "Open" shows: big actions, status, update row."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__, icons, util
from ..config import LANGUAGES
from ..paths import app_dir
from . import theme as T


class HomeWindow(QWidget):
    def __init__(self, controller):
        super().__init__(None)
        self.controller = controller
        self.setWindowTitle(__app_name__)
        self.setWindowIcon(icons.app_icon())
        self.resize(660, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(14)

        # ------------------------------------------------------------- header
        head = QHBoxLayout()
        logo = QLabel()
        pm = icons.lens_pixmap(56)
        logo.setPixmap(pm)
        head.addWidget(logo)
        titles = QVBoxLayout()
        t = QLabel(__app_name__)
        t.setObjectName("h1")
        titles.addWidget(t)
        sub = QLabel(f"Google Lens for Windows · v{__version__}")
        sub.setObjectName("muted")
        titles.addWidget(sub)
        head.addLayout(titles)
        head.addStretch(1)
        close_btn = QPushButton(icons.icon("close", 18), "")
        close_btn.setToolTip("Close the window (Glimpse keeps running in the tray)")
        close_btn.clicked.connect(self.hide)
        head.addWidget(close_btn)
        root.addLayout(head)

        # ------------------------------------------------------------- actions
        actions_card = QFrame()
        actions_card.setObjectName("card")
        grid = QGridLayout(actions_card)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setSpacing(10)
        hot = {}
        if controller is not None:
            hot = getattr(controller, "settings", None)
        hotkeys = (hot.hotkeys if hot else {}) or {}

        def action_button(icon_kind: str, label: str, hint: str, cb, primary: bool = False) -> QPushButton:
            b = QPushButton(icons.icon(icon_kind, 22), f"  {label}\n  {hint}")
            b.setMinimumHeight(64)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton { text-align: left; padding-left: 12px; font-size: 13px; }")
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(cb)
            return b

        def bind(fn):
            return (lambda: fn()) if controller is not None else (lambda: None)

        buttons = [
            (action_button("capture", "Capture area", hotkeys.get("capture", "Ctrl+Alt+L"), bind(lambda: controller.start_capture()), True), 0, 0),
            (action_button("translate", "Translate area", hotkeys.get("translate", "Ctrl+Alt+T"), bind(lambda: controller.start_capture(immediate="translate"))), 0, 1),
            (action_button("search", "Visual search", hotkeys.get("visual", "Ctrl+Alt+S"), bind(lambda: controller.start_capture(immediate="visual"))), 1, 0),
            (action_button("music", "Identify song", hotkeys.get("songid", "Ctrl+Alt+M"), bind(lambda: controller.identify_song())), 1, 1),
            (action_button("history", "History", "captures, texts, songs", bind(lambda: controller.show_history())), 2, 0),
            (action_button("settings", "Options", "hotkeys, engines, startup", bind(lambda: controller.show_settings())), 2, 1),
        ]
        for btn, r, c in buttons:
            grid.addWidget(btn, r, c)
        root.addWidget(actions_card)

        # ------------------------------------------------------------- status
        status_card = QFrame()
        status_card.setObjectName("card")
        sv = QVBoxLayout(status_card)
        sv.setContentsMargins(12, 10, 12, 10)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        sv.addWidget(self.status_label)

        row = QHBoxLayout()
        self.update_label = QLabel("Updates: not checked yet")
        self.update_label.setObjectName("muted")
        row.addWidget(self.update_label, 1)
        self.check_btn = QPushButton(icons.icon("info", 18), " Check for updates")
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.clicked.connect(bind(lambda: controller.check_for_updates(interactive=True)))
        row.addWidget(self.check_btn)
        sv.addLayout(row)
        root.addWidget(status_card)

        # ------------------------------------------------------------- footer
        foot = QHBoxLayout()
        data_btn = QPushButton("Open data folder")
        data_btn.clicked.connect(lambda: util.open_path(str(app_dir())))
        foot.addWidget(data_btn)
        foot.addStretch(1)
        quit_btn = QPushButton(icons.icon("close", 18), " Quit Glimpse")
        quit_btn.setObjectName("danger")
        quit_btn.clicked.connect(bind(lambda: controller.quit()))
        foot.addWidget(quit_btn)
        root.addLayout(foot)

        self._placed = False
        self.refresh_status()

    # ---------------------------------------------------------------- api
    def refresh_status(self) -> None:
        s = getattr(self.controller, "settings", None)
        if s is None:
            self.status_label.setText("")
            return
        ocr = {"windows": "Windows OCR", "tesseract": "Tesseract"}.get(s.ocr_engine, "Auto (Windows + Tesseract)")
        vis = "Google Lens" if s.visual_engine == "google" else "Yandex Images"
        audio = "system audio" if s.audio_source == "system" else "microphone"
        target = "auto (swap)" if s.target_lang == "auto" else LANGUAGES.get(s.target_lang, s.target_lang)
        self.status_label.setText(
            f"{ocr} · {vis} · translate → {target} · {audio} · {s.record_seconds}s listen"
        )

    def set_update_status(self, text: str) -> None:
        self.update_label.setText(text)

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
                    avail.top() + max(12, (avail.height() - self.height()) // 4),
                )
        self.refresh_status()

    def closeEvent(self, e):  # noqa: N802
        """Closing the window must not quit Glimpse — it lives in the tray."""
        e.ignore()
        self.hide()
