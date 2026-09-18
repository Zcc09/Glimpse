"""On-screen recording indicator: a click-through border around the region plus a
'REC 00:07 · Stop' pill placed outside it (so it does not end up in the video)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import icons
from . import theme as T

PILL_H = 46


def _mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


class RecordBorder(QWidget):
    """Two-pixel red frame around the recorded region; clicks pass straight through."""

    def __init__(self, rect: QRect):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setGeometry(rect)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        pen = QPen(QColor("#ff4d5a"))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


class RecordPill(QWidget):
    """The floating 'REC 00:07' pill with a Stop button."""

    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("record_pill")
        self.setStyleSheet(
            """
            QWidget#record_pill { background: #10171c; border: 1px solid #5a2a30; border-radius: 12px; }
            QLabel { background: transparent; }
            """
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.setSpacing(10)

        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #ff4d5a; font-size: 15px;")
        lay.addWidget(self.dot)

        self.time_label = QLabel("REC 00:00")
        self.time_label.setStyleSheet(f"color: {T.TEXT}; font-weight: 600;")
        lay.addWidget(self.time_label)

        self.size_label = QLabel("")
        self.size_label.setStyleSheet(f"color: {T.MUTED}; font-size: 11px;")
        lay.addWidget(self.size_label)

        stop = QPushButton(icons.icon("close", 14), "  Stop")
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.setStyleSheet(
            "QPushButton { background: #3a1e22; border: 1px solid #5a2a30; border-radius: 8px; "
            f"color: #ffd7da; padding: 4px 10px; }} QPushButton:hover {{ background: #4d2026; }}"
        )
        stop.clicked.connect(self.stop_requested.emit)
        lay.addWidget(stop)

        self.setFixedHeight(PILL_H)

        self._blink = QTimer(self)
        self._blink.timeout.connect(self._toggle_dot)
        self._blink_on = True

    def _toggle_dot(self) -> None:
        self._blink_on = not self._blink_on
        self.dot.setStyleSheet(f"color: {'#ff4d5a' if self._blink_on else '#7a2a31'}; font-size: 15px;")

    def set_elapsed(self, seconds: float) -> None:
        self.time_label.setText(f"REC {_mmss(seconds)}")

    def set_region(self, rect: QRect) -> None:
        self.size_label.setText(f"{rect.width()}×{rect.height()}")

    def start_blinking(self) -> None:
        self._blink.start(600)


class RecordingIndicator(QObject):
    """Owns the border + pill and keeps them where they belong on screen."""

    stop_requested = Signal()

    def __init__(self, region: QRect, parent=None):
        super().__init__(parent)
        self.region = QRect(region)
        self.border = RecordBorder(self.region)
        self.pill = RecordPill()
        self.pill.set_region(self.region)
        self.pill.stop_requested.connect(self.stop_requested.emit)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._started = 0.0

    def show(self) -> None:
        self.border.show()
        self._place_pill()
        self.pill.show()
        self.pill.raise_()
        self.pill.start_blinking()
        self.border.raise_()
        import time

        self._started = time.monotonic()
        self._timer.start(500)

    def set_elapsed(self, seconds: float) -> None:
        self.pill.set_elapsed(seconds)

    def _tick(self) -> None:
        import time

        self.pill.set_elapsed(time.monotonic() - self._started)

    def _place_pill(self) -> None:
        screen = QGuiApplication.screenAt(self.region.center()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        w = 250
        x = min(max(self.region.center().x() - w // 2, avail.left() + 6), max(avail.left(), avail.right() - w))
        y = self.region.bottom() + 8
        if y + PILL_H > avail.bottom():
            y = self.region.top() - PILL_H - 8
        if y < avail.top():
            y = max(avail.top() + 6, avail.bottom() - PILL_H - 6)  # full-screen: sit inside, bottom
        self.pill.setFixedWidth(w)
        self.pill.move(x, y)

    def close(self) -> None:
        self._timer.stop()
        self.pill.close()
        self.border.close()
