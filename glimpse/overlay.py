"""Snipping-Tool style overlay: freeze the desktop, drag a region, pick an action.

One window **per screen**: a single window spanning a mixed-DPI virtual desktop gets
scaled by Windows to the DPI of whichever monitor it was created on, which made the
other monitors look zoomed. Per-screen windows keep every screen's pixels 1:1, and the
drag is tracked in global logical coordinates so a selection can still span monitors.
"""
from __future__ import annotations

import ctypes
import time

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from . import icons
from .capture import Piece, ScreenShot
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
    """The floating 'Text / Translate / Search / Code / Save / Record / Copy' bar."""

    chosen = Signal(str)

    ACTIONS = [
        ("text", "Text"),
        ("translate", "Translate"),
        ("visual", "Search"),
        ("qr", "Code"),
        ("save", "Save"),
        ("record", "Record"),
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
            btn.setToolTip(self._tooltip(key))
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

    @staticmethod
    def _tooltip(key: str) -> str:
        return {
            "save": "Save the selection as a screenshot",
            "record": "Record the selection to a video",
            "copy": "Copy the image to the clipboard (Enter/Ctrl+C)",
            "qr": "Scan a QR code or barcode",
        }.get(key, key.capitalize())

    def width_hint(self) -> int:
        return BAR_PAD * 2 + BTN_W * len(self.ACTIONS) + BAR_GAP * (len(self.ACTIONS) + 2) + SEP_W + SEP_MARGIN * 2 + CLOSE_W

    def button_center(self, action: str) -> int:
        """X offset (from the bar's left edge) of a given button's centre — used by tests."""
        keys = [k for k, _ in self.ACTIONS]
        if action not in keys:
            return BAR_PAD + CLOSE_W // 2
        idx = keys.index(action)
        return BAR_PAD + idx * (BTN_W + BAR_GAP) + BTN_W // 2


class OverlayWindow(QWidget):
    """One freeze-frame window, covering exactly one screen."""

    def __init__(self, overlay: "Overlay", piece: Piece):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.overlay = overlay
        self.piece = piece
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(piece.rect)  # own screen only: Windows never stretches us
        self.setWindowTitle("Glimpse — select")

    # ------------------------------------------------------------ paint
    def paintEvent(self, event):  # noqa: N802
        ov = self.overlay
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # this screen's frozen content, pixel for pixel
        img = self.piece.pixmap.toImage()
        p.drawImage(QRect(0, 0, self.width(), self.height()), img)
        p.fillRect(self.rect(), QColor(4, 8, 11, 155))

        sel = ov.selection_global()
        local_sel = None
        if sel:
            inter = sel.intersected(self.piece.rect)
            if not inter.isEmpty():
                local_sel = inter.translated(-self.piece.rect.topLeft())

        if local_sel is not None:
            p.save()
            p.setClipRect(local_sel)
            p.drawImage(QRect(0, 0, self.width(), self.height()), img)
            p.restore()

            pen = QPen(QColor(T.BLUE))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(local_sel.adjusted(0, 0, -1, -1))

            # corner handles, only for corners that are really inside this screen
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffffff"))
            h = 7
            for cx, cy in (
                (local_sel.left(), local_sel.top()),
                (local_sel.right(), local_sel.top()),
                (local_sel.left(), local_sel.bottom()),
                (local_sel.right(), local_sel.bottom()),
            ):
                if 0 <= cx <= self.width() and 0 <= cy <= self.height():
                    p.drawRect(QRect(cx - h // 2, cy - h // 2, h, h))

            # size chip: drawn once, on the screen holding the selection's top-left corner
            if self.piece.rect.contains(sel.topLeft()) or local_sel.topLeft() == QPoint(0, 0):
                text = f"{sel.width()} × {sel.height()}"
                f = QFont("Segoe UI", 9)
                f.setBold(True)
                p.setFont(f)
                tw = p.fontMetrics().horizontalAdvance(text) + 16
                chip = QRect(local_sel.left(), max(0, local_sel.top() - 30), tw, 22)
                p.setBrush(QColor(8, 12, 15, 220))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(chip, 7, 7)
                p.setPen(QColor("#e8eef2"))
                p.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        else:
            # crosshair + hint only on the screen the cursor is on
            cursor_local = self.mapFromGlobal(QCursor.pos())
            if self.rect().contains(cursor_local):
                pen = QPen(QColor(255, 255, 255, 70))
                pen.setWidth(1)
                p.setPen(pen)
                p.drawLine(0, cursor_local.y(), self.width(), cursor_local.y())
                p.drawLine(cursor_local.x(), 0, cursor_local.x(), self.height())

                if not ov.dragging():
                    f = QFont("Segoe UI", 10)
                    p.setFont(f)
                    text = ov.hint_text()
                    tw = p.fontMetrics().horizontalAdvance(text) + 28
                    chip = QRect((self.width() - tw) // 2, 34, tw, 34)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(8, 12, 15, 215))
                    p.drawRoundedRect(chip, 10, 10)
                    p.setPen(QColor("#cfe0ea"))
                    p.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    # ------------------------------------------------------------ input → controller
    def mousePressEvent(self, e):  # noqa: N802
        self.overlay.window_pressed(self, e)

    def mouseMoveEvent(self, e):  # noqa: N802
        self.overlay.window_moved(self, e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self.overlay.window_released(self, e)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.overlay.window_double_clicked(self, e)

    def keyPressEvent(self, e):  # noqa: N802
        self.overlay.key_pressed(e)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self.raise_()


class Overlay(QObject):
    """Controller for the per-screen freeze-frame windows; owns the selection."""

    action_chosen = Signal(str, QRect)   # action key, selection (global logical coords)
    cancelled = Signal()

    def __init__(self, shot: ScreenShot, default_action: str = "text", immediate_action: str | None = None, parent=None):
        super().__init__(parent)
        self.shot = shot
        self.default_action = default_action or "text"
        self.immediate_action = immediate_action
        self.virtual_rect = shot.virtual_rect

        self._start: QPoint | None = None   # global logical coordinates
        self._end: QPoint | None = None
        self._dragging = False
        self._bar: ActionBar | None = None
        self._done = False

        self.windows: list[OverlayWindow] = [OverlayWindow(self, piece) for piece in shot.pieces]
        self.window = self.windows[0] if self.windows else None  # convenience/testing handle

    # ------------------------------------------------------------ helpers
    def hint_text(self) -> str:
        labels = dict(ActionBar.ACTIONS)
        d = labels.get(self.default_action, "Text")
        return f"Drag to select      •      Enter = {d}      •      Esc = cancel"

    def dragging(self) -> bool:
        return self._dragging

    def selection_global(self) -> QRect | None:
        if not self._start or not self._end:
            return None
        r = QRect(self._start, self._end).normalized()
        if r.width() < 4 or r.height() < 4:
            return None
        return r

    # kept for the smoke test / older callers
    def _sel_global(self) -> QRect | None:
        return self.selection_global()

    def focus_window_under_cursor(self) -> None:
        pos = QCursor.pos()
        target = next((w for w in self.windows if w.geometry().contains(pos)), self.window)
        if target is None:
            return
        for w in self.windows:
            w.raise_()
        target.activateWindow()
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        _force_foreground(target)

    def repaint_all(self) -> None:
        for w in self.windows:
            w.update()

    def render(self, target) -> None:
        """Render the primary window into a paint device (used by tests)."""
        if self.window is not None:
            self.window.render(target)

    # ------------------------------------------------------------ window events
    def window_pressed(self, win: OverlayWindow, e) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._hide_bar()
        g = win.mapToGlobal(e.position().toPoint())
        self._start = self._end = g
        self._dragging = True
        win.setFocus(Qt.FocusReason.MouseFocusReason)
        self.repaint_all()

    def window_moved(self, win: OverlayWindow, e) -> None:
        if self._dragging:
            self._end = win.mapToGlobal(e.position().toPoint())
        self.repaint_all()

    def window_released(self, win: OverlayWindow, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._end = win.mapToGlobal(e.position().toPoint())
        sel = self.selection_global()
        if not sel:
            log.info("drag too small — selection cleared")
            self._start = self._end = None
            self.repaint_all()
            return
        log.info("drag released with selection %s", sel)
        if self.immediate_action:
            self._emit(self.immediate_action)
            return
        self._show_bar(sel)
        self.repaint_all()

    def window_double_clicked(self, win: OverlayWindow, e) -> None:
        if self.selection_global():
            self._emit(self.default_action)

    def key_pressed(self, e) -> None:
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self._cancel()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.selection_global():
                self._emit(self.default_action)
        elif key == Qt.Key.Key_C and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.selection_global():
                self._emit("copy")
        else:
            e.ignore()

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

    # ------------------------------------------------------------ lifecycle
    def show(self) -> None:
        for w in self.windows:
            w.show()
        self.focus_window_under_cursor()
        self.repaint_all()

    def _emit(self, action: str) -> None:
        if self._done:
            return
        if action == "cancel":
            self._cancel()
            return
        sel = self.selection_global()
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

    def close(self) -> None:
        self._hide_bar()
        if self._bar is not None:
            self._bar.close()
            self._bar = None
        for w in self.windows:
            w.close()
        self.windows = []
        self.window = None
        self.deleteLater()
