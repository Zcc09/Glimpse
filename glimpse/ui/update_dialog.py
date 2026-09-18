"""Update available dialog: release notes, download progress, install."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .. import icons
from ..update import UpdateInfo, is_installed
from . import theme as T


class UpdateDialog(QDialog):
    """Progress arrives from the download worker thread — via a signal."""

    progress_sig = Signal(int, int)

    def __init__(self, controller, info: UpdateInfo, current: str):
        super().__init__(None)
        self.controller = controller
        self.info = info
        self.progress_sig.connect(self.set_progress)
        self.setWindowTitle("Glimpse — update available")
        self.setWindowIcon(icons.app_icon())
        self.resize(620, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Update available")
        title.setObjectName("h1")
        head.addWidget(title)
        chip = QLabel(f"v{info.version}")
        chip.setObjectName("chip")
        head.addWidget(chip)
        head.addStretch(1)
        cur = QLabel(f"you have v{current}")
        cur.setObjectName("muted")
        head.addWidget(cur)
        close_btn = QPushButton(icons.icon("close", 18), "")
        close_btn.clicked.connect(self.reject)
        head.addWidget(close_btn)
        root.addLayout(head)

        meta = QLabel(
            f"{info.title}\n"
            + (f"published {info.published_at[:10]}" if info.published_at else "")
        )
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        root.addWidget(meta)

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(info.notes or "(no release notes)")
        root.addWidget(notes, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

        row = QHBoxLayout()
        self.page_btn = QPushButton("Open release page")
        self.page_btn.clicked.connect(lambda: self.controller and self.controller.open_url(info.page_url))
        row.addWidget(self.page_btn)
        row.addStretch(1)
        later = QPushButton("Later")
        later.clicked.connect(self.reject)
        row.addWidget(later)
        self.install_btn = QPushButton(icons.icon("save", 18), " Install update" if is_installed() else " Download")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self._install)
        row.addWidget(self.install_btn)
        root.addLayout(row)

        self._placed = False

    # ---------------------------------------------------------------- download
    def _install(self) -> None:
        asset = self.info.installer_asset()
        if asset is None or not asset.url:
            self.status.setText("No installer asset in this release — open the release page instead.")
            return
        self.install_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText(f"Downloading {asset.name}…")
        if self.controller:
            self.controller.download_update(self.info, self)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = int(done * 100 / total)
            self.progress.setValue(pct)
            self.status.setText(f"Downloading… {done // (1024*1024)} / {total // (1024*1024)} MB")
        else:
            self.status.setText(f"Downloading… {done // (1024*1024)} MB")

    def download_finished(self, path: str) -> None:
        self.progress.setValue(100)
        self.status.setText(f"Downloaded to {path}")
        if self.controller:
            self.controller.finish_update(path, self)

    def download_failed(self, message: str) -> None:
        self.install_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setStyleSheet(f"color: {T.DANGER};")
        self.status.setText(f"Download failed: {message}")

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
