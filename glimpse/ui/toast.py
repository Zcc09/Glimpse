"""Transient toast notifications (bottom-right, stacked, click-through-free)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme as T

KIND_COLORS = {"info": T.BLUE, "success": T.OK, "error": T.DANGER, "warn": T.WARN}


class Toast(QFrame):
    def __init__(self, title: str, body: str = "", kind: str = "info", action_label: str | None = None, action_cb=None, timeout: int = 3200):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._action_cb = action_cb

        accent = KIND_COLORS.get(kind, T.BLUE)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        card = QFrame()
        card.setObjectName("toast_card")
        card.setStyleSheet(
            f"""
            QFrame#toast_card {{
                background: #131a1f;
                border: 1px solid #2b3b45;
                border-left: 3px solid {accent};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; }}
            """
        )
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)

        self.title = QLabel(title)
        self.title.setStyleSheet(f"color: {T.TEXT}; font-weight: 600; font-size: 13px; background: transparent;")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)

        if body:
            self.body = QLabel(body)
            self.body.setStyleSheet(f"color: {T.MUTED}; font-size: 12px; background: transparent;")
            self.body.setWordWrap(True)
            lay.addWidget(self.body)

        if action_label and action_cb:
            btn = QPushButton(action_label)
            btn.setObjectName("link")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"QPushButton {{ color: {T.BLUE_HI}; background: transparent; border: none; padding: 2px 0; text-align: left; }} QPushButton:hover {{ color: #9cc6ff; }}")
            btn.clicked.connect(self._run_action)
            lay.addWidget(btn)

        self.setFixedWidth(380)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timeout = timeout

    def _run_action(self) -> None:
        try:
            if self._action_cb:
                self._action_cb()
        finally:
            self.close()

    def mousePressEvent(self, e):  # noqa: N802
        if self._action_cb:
            self._run_action()
        else:
            self.close()

    def show_toast(self) -> None:
        self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(self._timeout)


class ToastManager(QObject):
    def __init__(self, parent=None, max_toasts: int = 3):
        super().__init__(parent)
        self.toasts: list[Toast] = []
        self.max_toasts = max_toasts

    def show(self, title: str, body: str = "", kind: str = "info", timeout: int = 3200, action_label: str | None = None, action_cb=None) -> Toast:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None  # type: ignore[return-value]
        t = Toast(title, body, kind, action_label, action_cb, timeout)
        self.toasts.append(t)
        while len(self.toasts) > self.max_toasts:
            old = self.toasts.pop(0)
            old.close()
        t.destroyed.connect(lambda *_: self._remove(t))
        t.show_toast()
        self._reposition(screen)
        return t

    def _remove(self, t: Toast) -> None:
        if t in self.toasts:
            self.toasts.remove(t)

    def _reposition(self, screen) -> None:
        avail = screen.availableGeometry()
        y = avail.bottom() - 12
        for t in reversed(self.toasts):
            if not t.isVisible():
                continue
            w = t.width()
            h = t.height()
            t.move(QPoint(avail.right() - w + 1, y - h))
            y -= h + 10
