"""Vector-drawn icons (SyncPlayer family style: dark tile, blue+teal panels, white glyph)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .ui import theme as T

TILE_BG = "#12181d"


def _painter(pm: QPixmap) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return p


# ------------------------------------------------------------------ app tile
def lens_pixmap(size: int, tile: bool = True) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = _painter(pm)
    s = float(size)

    if tile:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(TILE_BG))
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)

        p.setBrush(QColor(T.BLUE))
        p.drawRoundedRect(QRectF(s * 0.09, s * 0.09, s * 0.45, s * 0.45), s * 0.13, s * 0.13)
        p.setBrush(QColor(T.TEAL))
        p.drawRoundedRect(QRectF(s * 0.46, s * 0.46, s * 0.45, s * 0.45), s * 0.13, s * 0.13)

    # white magnifier
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.2, s * 0.078))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy, rad = s * 0.445, s * 0.43, s * 0.235
    p.drawEllipse(QPointF(cx, cy), rad, rad)
    ang = math.pi * 0.25  # bottom-right diagonal
    x0, y0 = cx + math.cos(ang) * rad, cy + math.sin(ang) * rad
    x1, y1 = cx + math.cos(ang) * (rad + s * 0.21), cy + math.sin(ang) * (rad + s * 0.21)
    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    p.end()
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(lens_pixmap(size))
    return ic


def tray_icon() -> QIcon:
    ic = QIcon()
    ic.addPixmap(lens_pixmap(16))
    ic.addPixmap(lens_pixmap(32))
    ic.addPixmap(lens_pixmap(64))
    return ic


def tile_icon(size: int = 20) -> QIcon:
    """The app tile itself (used for tray 'Open')."""
    ic = QIcon()
    ic.addPixmap(lens_pixmap(size))
    ic.addPixmap(lens_pixmap(size * 2))
    return ic


# ------------------------------------------------------------------ glyphs
def _stroke_pen(p: QPainter, color: QColor, s: float, width: float = 0.085) -> QPen:
    pen = QPen(color)
    pen.setWidthF(max(1.3, s * width))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    return pen


def glyph_pixmap(kind: str, size: int = 22, color: str = "#ffffff") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = _painter(pm)
    s = float(size)
    c = QColor(color)

    if kind == "text":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        for i, (y, w) in enumerate(((0.26, 0.68), (0.46, 0.52), (0.66, 0.36))):
            p.drawRoundedRect(QRectF(s * 0.16, s * y, s * w, s * 0.1), s * 0.05, s * 0.05)

    elif kind == "translate":
        _stroke_pen(p, c, s, 0.07)
        f = QFont("Segoe UI")
        f.setPixelSize(int(s * 0.6))
        f.setBold(True)
        p.setFont(f)
        p.setPen(c)
        p.drawText(QRectF(0, 0, s * 0.56, s), Qt.AlignmentFlag.AlignCenter, "A")
        p.drawText(QRectF(s * 0.44, 0, s * 0.56, s), Qt.AlignmentFlag.AlignCenter, "ع")

    elif kind == "search":
        _stroke_pen(p, c, s)
        cx, cy, r = s * 0.42, s * 0.4, s * 0.26
        p.drawEllipse(QPointF(cx, cy), r, r)
        ang = math.pi * 0.25
        p.drawLine(
            QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r),
            QPointF(cx + math.cos(ang) * r * 2.05, cy + math.sin(ang) * r * 2.05),
        )

    elif kind == "qr":
        _stroke_pen(p, c, s, 0.075)
        for x, y in ((0.12, 0.12), (0.54, 0.12), (0.12, 0.54)):
            p.drawRoundedRect(QRectF(s * x, s * y, s * 0.34, s * 0.34), s * 0.06, s * 0.06)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        for x, y in ((0.58, 0.58), (0.76, 0.58), (0.58, 0.76), (0.76, 0.76)):
            p.drawRoundedRect(QRectF(s * x, s * y, s * 0.12, s * 0.12), s * 0.03, s * 0.03)

    elif kind == "copy":
        _stroke_pen(p, c, s, 0.075)
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.12, s * 0.5, s * 0.5), s * 0.08, s * 0.08)
        p.drawRoundedRect(QRectF(s * 0.38, s * 0.38, s * 0.5, s * 0.5), s * 0.08, s * 0.08)

    elif kind == "close":
        _stroke_pen(p, c, s, 0.095)
        p.drawLine(QPointF(s * 0.22, s * 0.22), QPointF(s * 0.78, s * 0.78))
        p.drawLine(QPointF(s * 0.78, s * 0.22), QPointF(s * 0.22, s * 0.78))

    elif kind == "music":
        _stroke_pen(p, c, s, 0.08)
        for cx in (0.3, 0.66):
            p.drawEllipse(QPointF(s * cx, s * 0.75), s * 0.13, s * 0.1)
            p.drawLine(QPointF(s * (cx + 0.13), s * 0.75), QPointF(s * (cx + 0.13), s * 0.24))
        p.drawLine(QPointF(s * 0.43, s * 0.24), QPointF(s * 0.79, s * 0.3))

    elif kind == "history":
        _stroke_pen(p, c, s, 0.075)
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.34, s * 0.34)
        p.drawLine(QPointF(s * 0.5, s * 0.5), QPointF(s * 0.5, s * 0.3))
        p.drawLine(QPointF(s * 0.5, s * 0.5), QPointF(s * 0.66, s * 0.58))

    elif kind == "settings":
        _stroke_pen(p, c, s, 0.07)
        for y, kx in ((0.3, 0.38), (0.5, 0.62), (0.7, 0.46)):
            p.drawLine(QPointF(s * 0.14, s * y), QPointF(s * 0.86, s * y))
            p.setBrush(QColor(TILE_BG))
            p.drawEllipse(QPointF(s * kx, s * y), s * 0.095, s * 0.095)
            p.setBrush(Qt.BrushStyle.NoBrush)

    elif kind == "info":
        _stroke_pen(p, c, s, 0.075)
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.35, s * 0.35)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(s * 0.5, s * 0.31), s * 0.055, s * 0.055)
        _stroke_pen(p, c, s, 0.085)
        p.drawLine(QPointF(s * 0.5, s * 0.45), QPointF(s * 0.5, s * 0.7))

    elif kind == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        path = QPainterPath()
        path.moveTo(s * 0.3, s * 0.2)
        path.lineTo(s * 0.82, s * 0.5)
        path.lineTo(s * 0.3, s * 0.8)
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "capture":
        _stroke_pen(p, c, s, 0.085)
        L, o = s * 0.26, s * 0.14
        # four corner brackets
        for cx, cy, dx, dy in (
            (o, o, 1, 1),
            (s - o, o, -1, 1),
            (o, s - o, 1, -1),
            (s - o, s - o, -1, -1),
        ):
            p.drawLine(QPointF(cx, cy + dy * L), QPointF(cx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx * L, cy))
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.08, s * 0.08)

    elif kind == "image":
        _stroke_pen(p, c, s, 0.072)
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.18, s * 0.76, s * 0.64), s * 0.08, s * 0.08)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(s * 0.34, s * 0.37), s * 0.06, s * 0.06)
        path = QPainterPath()
        path.moveTo(s * 0.18, s * 0.74)
        path.lineTo(s * 0.42, s * 0.5)
        path.lineTo(s * 0.56, s * 0.62)
        path.lineTo(s * 0.68, s * 0.52)
        path.lineTo(s * 0.84, s * 0.74)
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "save":
        _stroke_pen(p, c, s, 0.08)
        p.drawLine(QPointF(s * 0.5, s * 0.14), QPointF(s * 0.5, s * 0.56))
        p.drawLine(QPointF(s * 0.34, s * 0.42), QPointF(s * 0.5, s * 0.58))
        p.drawLine(QPointF(s * 0.66, s * 0.42), QPointF(s * 0.5, s * 0.58))
        p.drawLine(QPointF(s * 0.18, s * 0.72), QPointF(s * 0.18, s * 0.84))
        p.drawLine(QPointF(s * 0.18, s * 0.84), QPointF(s * 0.82, s * 0.84))
        p.drawLine(QPointF(s * 0.82, s * 0.84), QPointF(s * 0.82, s * 0.72))

    elif kind == "record":
        # a filled dot inside a ring — the universal "recording" mark
        _stroke_pen(p, c, s, 0.075)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.32, s * 0.32)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c))
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.17, s * 0.17)

    elif kind == "trash":
        _stroke_pen(p, c, s, 0.074)
        p.drawLine(QPointF(s * 0.18, s * 0.28), QPointF(s * 0.82, s * 0.28))
        p.drawLine(QPointF(s * 0.4, s * 0.28), QPointF(s * 0.42, s * 0.18))
        p.drawLine(QPointF(s * 0.6, s * 0.28), QPointF(s * 0.58, s * 0.18))
        p.drawLine(QPointF(s * 0.42, s * 0.18), QPointF(s * 0.58, s * 0.18))
        path = QPainterPath()
        path.moveTo(s * 0.26, s * 0.32)
        path.lineTo(s * 0.3, s * 0.84)
        path.lineTo(s * 0.7, s * 0.84)
        path.lineTo(s * 0.74, s * 0.32)
        p.drawPath(path)

    elif kind == "swap":
        _stroke_pen(p, c, s, 0.082)
        p.drawLine(QPointF(s * 0.18, s * 0.34), QPointF(s * 0.8, s * 0.34))
        p.drawLine(QPointF(s * 0.66, s * 0.2), QPointF(s * 0.8, s * 0.34))
        p.drawLine(QPointF(s * 0.82, s * 0.66), QPointF(s * 0.2, s * 0.66))
        p.drawLine(QPointF(s * 0.34, s * 0.52), QPointF(s * 0.2, s * 0.66))

    p.end()
    return pm


def icon(kind: str, size: int = 22, color: str = "#ffffff") -> QIcon:
    ic = QIcon()
    ic.addPixmap(glyph_pixmap(kind, size, color))
    ic.addPixmap(glyph_pixmap(kind, int(size * 2), color))
    return ic


# action-bar icons (drawn on the dark bar, so default white)
ACTION_ICON_KINDS = {
    "text": "text",
    "translate": "translate",
    "visual": "search",
    "qr": "qr",
    "copy": "copy",
    "save": "save",
    "record": "record",
    "cancel": "close",
}


def action_icon(action: str, size: int = 20) -> QIcon:
    return icon(ACTION_ICON_KINDS.get(action, "search"), size)


# ------------------------------------------------------------------ tray/other
def tray_menu_icons() -> dict:
    return {
        "capture": icon("capture", 20),
        "translate": icon("translate", 20),
        "visual": icon("search", 20),
        "songid": icon("music", 20),
        "history": icon("history", 20),
        "settings": icon("settings", 20),
        "update": icon("save", 20),
        "save": icon("save", 20),
        "record": icon("record", 20),
        "folder": icon("history", 20),
        "about": icon("info", 20),
        "quit": icon("close", 20),
    }


def dot_pixmap(color: str, size: int = 10) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = _painter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(0, 0, size, size))
    p.end()
    return pm
