"""Snipping-Tool style overlay: freeze the desktop, drag a region, pick an action."""
from __future__ import annotations

import ctypes
import time

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from . import icons
from .capture import ScreenShot
from .log import log
from .ui import theme as T

# Layout constants — the desktop E2E test computes button positions from these.
BAR_PAD = 8
BTN_W = 96
BTN_H = 46
BAR_GAP = 6
SEP_W = 1
SEP_MARGIN = 4
CLOSE_W = 40


def _force_foreground(widget: QWidget) -> None:
    """Make our window the foreground window (a hotkey-launched process has no foreground rights)."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        hwnd = int(widget.winId())
    except RuntimeError:
        return
    for _attempt in range(3):
        try:
            fg = user32.GetForegroundWindow()
            if fg == hwnd:
                return
            tid_fg = user32.GetWindowThreadProcessId(fg, None)
            tid_me = kernel32.GetCurrentThreadId()
            attached = False
            if tid_fg and tid_fg != tid_me:
                attached = bool(user32.AttachThreadInput(tid_fg, tid_me, True))
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(tid_fg, tid_me, False)
            if user32.GetForegroundWindow() == hwnd:
                return
            # last resort: SwitchToThisWindow (undocumented, widely used)
            try:
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            log.debug("force foreground failed: %s", e)
            return
        time.sleep(0.05)


class ActionBar(QWidget):
    """The floating 'Text / Translate / Search / Code / Copy' bar under the selection."""

    chosen = Signal(str)

    ACTIONS = [
        ("text", "Text"),
        ("translate", "Translate"),
        ("visual", "Search"),
        ("qr", "Code"),
        ("copy", "Copy"),
    ]

    def __init__(self, default_action: str = "text", parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("action_bar")
        self.setStyleSheet(
            f"""
            QWidget#action_bar {{
                background: #10171c;
                border: 1px solid #2d3f4a;
                border-radius: 12px;
            }}
            QPushButton {{
                background: transparent; border: none; border-radius: 9px;
                color: #cfe0ea; font-size: 12px; padding: 4px 2px;
            }}
            QPushButton:hover {{ background: #1d3140; color: white; }}
            QPushButton:pressed {{ background: #14344f; }}
            QPushButton#default_action {{ background: #1b3350; color: white; }}
            QPushButton#close_btn {{ color: #93a4ae; }}
            QPushButton#close_btn:hover {{ background: #3a1e22; color: #ff9aa2; }}
            """
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(BAR_PAD, BAR_PAD, BAR_PAD, BAR_PAD)
        lay.setSpacing(BAR_GAP)

        for key, label in self.ACTIONS:
            btn = QPushButton(icons.icon(icons.ACTION_ICON_KINDS[key], 20), f"  {label}")
            btn.setFixedSize(BTN_W, BTN_H)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if key == default_action:
                btn.setObjectName("default_action")
            btn.clicked.connect(lambda _=False, k=key: self.chosen.emit(k))
            lay.addWidget(btn)

        sep = QWidget()
        sep.setFixedWidth(SEP_W)
        sep.setStyleSheet("background: #26343c; border-radius: 1px;")
        lay.addSpacing(SEP_MARGIN)
        lay.addWidget(sep)
        lay.addSpacing(SEP_MARGIN)

        close = QPushButton(icons.icon("close", 18), "")
        close.setObjectName("close_btn")
        close.setFixedSize(CLOSE_W, BTN_H)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setToolTip("Cancel (Esc)")
        close.clicked.connect(lambda: self.chosen.emit("cancel"))
        lay.addWidget(close)

        self.setFixedHeight(BTN_H + BAR_PAD * 2 + 2)

    def width_hint(self) -> int:
        return BAR_PAD * 2 + BTN_W * len(self.ACTIONS) + BAR_GAP * (len(self.ACTIONS) + 2) + SEP_W + SEP_MARGIN * 2 + CLOSE_W

    def button_center(self, action: str) -> int:
        """X offset (from the bar's left edge) of a given button's centre — used by tests."""
        keys = [k for k, _ in self.ACTIONS]
        if action not in keys:
            return BAR_PAD + CLOSE_W // 2
        idx = keys.index(action)
        return BAR_PAD + idx * (BTN_W + BAR_GAP) + BTN_W // 2


class Overlay(QWidget):
    """Full virtual-desktop freeze-frame selector."""

    action_chosen = Signal(str, QRect)   # action key, selection (global logical coords)
    cancelled = Signal()

    def __init__(self, shot: ScreenShot, default_action: str = "text", immediate_action: str | None = None, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.shot = shot
        self.default_action = default_action or "text"
        self.immediate_action = immediate_action
        self.virtual_rect = shot.virtual_rect
        self.setGeometry(shot.virtual_rect)

        self._start: QPoint | None = None
        self._end: QPoint | None = None
        self._dragging = False
        self._bar: ActionBar | None = None
        self._done = False

        self._hint = self._make_hint_text()

    # ------------------------------------------------------------ helpers
    def _make_hint_text(self) -> str:
        labels = dict(ActionBar.ACTIONS)
        d = labels.get(self.default_action, "Text")
        return f"Drag to select      •      Enter = {d}      •      Esc = cancel"

    def _sel_global(self) -> QRect | None:
        if not self._start or not self._end:
            return None
        g0 = self.mapToGlobal(self._start)
        g1 = self.mapToGlobal(self._end)
        r = QRect(g0, g1).normalized()
        if r.width() < 4 or r.height() < 4:
            return None
        return r

    def _sel_local(self) -> QRect | None:
        r = self._sel_global()
        return r.translated(-self.virtual_rect.topLeft()) if r else None

    # ------------------------------------------------------------ paint
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        for piece in self.shot.pieces:
            r = self.shot.local_rect(piece)
            p.drawImage(r, piece.pixmap.toImage())

        p.fillRect(self.rect(), QColor(4, 8, 11, 155))

        sel = self._sel_local()
        if sel:
            # brighten the selected area again
            p.save()
            p.setClipRect(sel)
            for piece in self.shot.pieces:
                r = self.shot.local_rect(piece)
                p.drawImage(r, piece.pixmap.toImage())
            p.restore()

            pen = QPen(QColor(T.BLUE))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel.adjusted(0, 0, -1, -1))

            # corner handles
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffffff"))
            h = 7
            for cx, cy in (
                (sel.left(), sel.top()),
                (sel.right(), sel.top()),
                (sel.left(), sel.bottom()),
                (sel.right(), sel.bottom()),
            ):
                p.drawRect(QRect(cx - h // 2, cy - h // 2, h, h))

            # size chip above the selection
            text = f"{sel.width()} × {sel.height()}"
            f = QFont("Segoe UI", 9)
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(text) + 16
            chip = QRect(sel.left(), max(0, sel.top() - 30), tw, 22)
            p.setBrush(QColor(8, 12, 15, 220))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(chip, 7, 7)
            p.setPen(QColor("#e8eef2"))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        else:
            # crosshair at the cursor
            pos = self.mapFromGlobal(QCursor.pos())
            pen = QPen(QColor(255, 255, 255, 70))
            pen.setWidth(1)
            p.setPen(pen)
            p.drawLine(0, pos.y(), self.width(), pos.y())
            p.drawLine(pos.x(), 0, pos.x(), self.height())

            # hint chip top-centre
            if not self._dragging:
                f = QFont("Segoe UI", 10)
                p.setFont(f)
                text = self._hint
                tw = p.fontMetrics().horizontalAdvance(text) + 28
                chip = QRect((self.width() - tw) // 2, 34, tw, 34)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(8, 12, 15, 215))
                p.drawRoundedRect(chip, 10, 10)
                p.setPen(QColor("#cfe0ea"))
                p.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._hide_bar()
        self._start = e.position().toPoint()
        self._end = self._start
        self._dragging = True
        self.update()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._dragging:
            self._end = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._end = e.position().toPoint()
        sel = self._sel_global()
        if not sel:
            log.info("drag too small — selection cleared")
            self._start = self._end = None
            self.update()
            return
        log.info("drag released with selection %s", sel)
        if self.immediate_action:
            self._emit(self.immediate_action)
            return
        self._show_bar(sel)
        self.update()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if self._sel_global():
            self._emit(self.default_action)

    # ------------------------------------------------------------ keyboard
    def keyPressEvent(self, e):  # noqa: N802
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self._cancel()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._sel_global():
                self._emit(self.default_action)
        elif key == Qt.Key.Key_C and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._sel_global():
                self._emit("copy")
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------ action bar
    def _show_bar(self, sel_global: QRect) -> None:
        if self._bar is None:
            self._bar = ActionBar(self.default_action)
            self._bar.chosen.connect(self._emit)
        bar = self._bar
        w = bar.width_hint()
        h = bar.height()
        screen = QGuiApplication.screenAt(sel_global.center()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = min(max(sel_global.left(), avail.left()), max(avail.left(), avail.right() - w + 1))
        y = sel_global.bottom() + 10
        if y + h > avail.bottom():
            y = sel_global.top() - h - 10
        y = max(avail.top(), y)
        bar.move(x, y)
        bar.show()
        bar.raise_()

    def _hide_bar(self) -> None:
        if self._bar is not None:
            self._bar.hide()

    def _emit(self, action: str) -> None:
        if self._done:
            return
        if action == "cancel":
            self._cancel()
            return
        sel = self._sel_global()
        if not sel:
            return
        self._done = True
        self._hide_bar()
        log.info("overlay action %s on %sx%s", action, sel.width(), sel.height())
        self.action_chosen.emit(action, sel)
        self.close()

    def _cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._hide_bar()
        self.cancelled.emit()
        self.close()

    # ------------------------------------------------------------ lifecycle
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        _force_foreground(self)

    def closeEvent(self, e):  # noqa: N802
        self._hide_bar()
        if self._bar is not None:
            self._bar.close()
            self._bar = None
        super().closeEvent(e)
