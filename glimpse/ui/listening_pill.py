"""'Listening…' pill shown while recording audio for song identification."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import icons
from . import theme as T


class ListeningPill(QWidget):
    """Frameless bottom-centre pill: pulsing dot + countdown + cancel."""

    progress = Signal(float)          # 0..1 from the recording thread
    phase = Signal(str)               # 'recording' | 'identifying'

    def __init__(self, seconds: int = 8, source_label: str = "System audio", parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.seconds = max(3, int(seconds))
        self._phase = "recording"
        self._frac = 0.0
        self._pulse = 0.0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        self.dot = _Dot(self)
        lay.addWidget(self.dot)

        self.label = QLabel("Listening…")
        self.label.setStyleSheet(f"color: {T.TEXT}; font-weight: 600; background: transparent;")
        lay.addWidget(self.label)

        self.sub = QLabel(f"from {source_label}")
        self.sub.setStyleSheet(f"color: {T.MUTED}; background: transparent;")
        lay.addWidget(self.sub)

        self.cancel = QPushButton(icons.icon("close", 16), "")
        self.cancel.setFixedSize(28, 28)
        self.cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel.setStyleSheet("QPushButton { background: #1c262c; border: 1px solid #2a3a42; border-radius: 14px; } QPushButton:hover { background: #3a1e22; }")
        self.cancel.setToolTip("Stop (Esc)")
        self.cancel.clicked.connect(self.close)
        lay.addWidget(self.cancel)

        self.progress.connect(self.set_progress)
        self.phase.connect(self.set_phase)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_timer.start(60)

    # -------------------------------------------------- API (thread-safe signals)
    def set_progress(self, frac: float) -> None:
        self._frac = max(0.0, min(1.0, float(frac)))
        remaining = max(0, int(round(self.seconds * (1 - self._frac))))
        if self._phase == "recording":
            self.label.setText(f"Listening… {remaining}s")
        self.update()

    def set_phase(self, phase: str) -> None:
        self._phase = phase
        if phase == "identifying":
            self.label.setText("Identifying…")
            self.sub.setText("asking Shazam")
        self.update()

    def _tick_pulse(self) -> None:
        self._pulse = (self._pulse + 0.06) % 1.0
        self.dot.update()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    # -------------------------------------------------- paint
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QColor("#2d3f4a"))
        p.setBrush(QColor(16, 23, 28, 240))
        p.drawRoundedRect(r, 14, 14)
        p.end()

    def show_pill(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.adjustSize()
            x = avail.center().x() - self.width() // 2
            y = avail.bottom() - self.height() - 64
            self.move(x, y)
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)


class _Dot(QWidget):
    def __init__(self, pill: ListeningPill):
        super().__init__()
        self.pill = pill
        self.setFixedSize(16, 16)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        import math

        base = 3.5
        grow = 1.0 + 1.6 * (0.5 + 0.5 * math.sin(self.pill._pulse * 2 * math.pi))
        color = QColor(T.TEAL)
        color.setAlphaF(0.55 + 0.45 * (grow - 1.0) / 1.6)
        p.setBrush(color)
        c = self.rect().center()
        rad = base * grow
        p.drawEllipse(c, rad, rad)
        p.end()
