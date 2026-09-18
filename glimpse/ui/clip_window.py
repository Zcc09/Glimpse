"""Clip window: preview a recording, trim it, or send a frame to Google Lens."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import icons, util
from ..log import log
from ..record import frame_at, probe_duration, trim_clip
from . import theme as T


def _mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


def open_in_player(path: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:  # noqa: BLE001
        log.warning("could not open %s: %s", path, e)


class ClipWindow(QDialog):
    """Trim / inspect / share one recorded clip."""

    def __init__(self, controller, path: str, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.path = str(path)
        self.duration = max(0.1, probe_duration(self.path))
        name = Path(self.path).name
        self.setWindowTitle(f"Glimpse — clip: {name}")
        self.setWindowIcon(icons.app_icon())
        self.resize(760, 560)
        self._frame_cache: dict[int, QPixmap] = {}
        self._last_disk = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title = QLabel(name)
        title.setObjectName("h1")
        root.addWidget(title)

        size_mb = Path(self.path).stat().st_size / 1e6 if Path(self.path).exists() else 0.0
        self.meta = QLabel(f"{_mmss(self.duration)} · {size_mb:.1f} MB · {self.path}")
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)
        root.addWidget(self.meta)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(300)
        self.preview.setStyleSheet(
            f"background: #0b1116; border: 1px solid {T.BORDER}; border-radius: 10px; color: {T.MUTED};"
        )
        self.preview.setText("loading preview…")
        root.addWidget(self.preview, 1)

        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(1, int(self.duration * 100)))
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderReleased.connect(lambda: self._show_frame(self.slider.value() / 100.0))
        row.addWidget(self.slider, 1)
        self.pos_label = QLabel(_mmss(0))
        self.pos_label.setObjectName("muted")
        row.addWidget(self.pos_label)
        root.addLayout(row)

        trim_box = QWidget()
        trim_row = QHBoxLayout(trim_box)
        trim_row.setContentsMargins(0, 0, 0, 0)
        trim_row.addWidget(QLabel("Trim"))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0.0, max(0.1, self.duration - 0.1))
        self.start_spin.setDecimals(1)
        self.start_spin.setSingleStep(0.5)
        self.start_spin.setSuffix(" s")
        trim_row.addWidget(self.start_spin)
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.1, self.duration)
        self.end_spin.setDecimals(1)
        self.end_spin.setSingleStep(0.5)
        self.end_spin.setSuffix(" s")
        self.end_spin.setValue(self.duration)
        trim_row.addWidget(self.end_spin)
        self.trim_btn = QPushButton(icons.icon("save", 16), "  Trim && save as…")
        self.trim_btn.clicked.connect(self._trim)
        trim_row.addWidget(self.trim_btn)
        trim_row.addStretch(1)
        root.addWidget(trim_box)

        buttons = QHBoxLayout()
        play = QPushButton(icons.icon("play", 16), "  Open")
        play.clicked.connect(lambda: open_in_player(self.path))
        buttons.addWidget(play)
        folder = QPushButton("Open folder")
        folder.clicked.connect(lambda: util.open_path(str(Path(self.path).parent)))
        buttons.addWidget(folder)
        copy_path = QPushButton("Copy path")
        copy_path.clicked.connect(self._copy_path)
        buttons.addWidget(copy_path)
        lens = QPushButton(icons.icon("search", 16), "  Send frame to Lens")
        lens.setToolTip("Upload the current frame to Google Lens")
        lens.clicked.connect(self._send_to_lens)
        buttons.addWidget(lens)
        buttons.addStretch(1)
        delete = QPushButton(icons.icon("trash", 16), "  Delete")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        buttons.addWidget(delete)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self._show_frame(0.0)

    # ------------------------------------------------------------ preview
    def _on_slider(self, value: int) -> None:
        self.pos_label.setText(f"{_mmss(value / 100.0)} / {_mmss(self.duration)}")

    def _show_frame(self, seconds: float) -> None:
        key = int(round(seconds * 2))  # half-second cache buckets
        pix = self._frame_cache.get(key)
        if pix is None:
            img = frame_at(self.path, seconds)
            if img is None:
                self.preview.setText("no preview available")
                return
            pix = QPixmap.fromImage(img)
            self._frame_cache[key] = pix
        self.preview.setPixmap(
            pix.scaled(
                self.preview.width() or 700,
                self.preview.height() or 320,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _current_seconds(self) -> float:
        return self.slider.value() / 100.0

    # ------------------------------------------------------------ actions
    def _copy_path(self) -> None:
        util.copy_text(self.path)
        self.status.setText("path copied")

    def _trim(self) -> None:
        start, end = self.start_spin.value(), self.end_spin.value()
        if end <= start + 0.2:
            self.status.setText("the end must be at least 0.2 s after the start")
            return
        out = str(Path(self.path).with_name(f"{Path(self.path).stem}-trim{Path(self.path).suffix}"))
        self.status.setText("trimming…")
        self.trim_btn.setEnabled(False)

        def work() -> bool:
            return trim_clip(self.path, out, start, end)

        def ok(done: bool) -> None:
            self.trim_btn.setEnabled(True)
            if not done:
                self.status.setText("trim failed (see the log)")
                return
            dur = probe_duration(out)
            self.status.setText(f"saved {Path(out).name} ({_mmss(dur)})")
            if self.controller:
                self.controller.notify("Clip trimmed", f"{Path(out).name} · {_mmss(dur)}")
                self.controller.open_clip(out)

        def err(kind: str, msg: str, tb: str) -> None:
            self.trim_btn.setEnabled(True)
            self.status.setText(f"trim failed: {msg}")

        util.run_bg(work, ok, err, name="trim")

    def _send_to_lens(self) -> None:
        img = frame_at(self.path, self._current_seconds())
        if img is None:
            self.status.setText("could not read a frame from this clip")
            return
        self.status.setText("uploading the frame to Google Lens…")

        def work() -> str:
            from ..capture import png_bytes
            from ..visual import lens_upload

            return lens_upload(png_bytes(img))

        def ok(url: str) -> None:
            self.status.setText("opened in your browser")
            if self.controller:
                self.controller.open_url(url)

        def err(kind: str, msg: str, tb: str) -> None:
            self.status.setText(f"Lens upload failed: {msg}")

        util.run_bg(work, ok, err, name="clip-lens")

    def _delete(self) -> None:
        answer = QMessageBox.question(
            self,
            "Delete clip",
            f"Delete {Path(self.path).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(self.path)
            self.status.setText("deleted")
            self.close()
        except OSError as e:
            self.status.setText(f"could not delete: {e}")
