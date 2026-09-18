"""Screen capture: full-desktop grab (all monitors, native resolution) and region crops.

Qt gives us device pixels from QScreen.grabWindow(); the selection arrives in
logical (device-independent) coordinates, so every crop is scaled by the
screen's devicePixelRatio. Multi-monitor selections with mixed DPRs are
stitched on a canvas normalised to the highest DPR.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap

from .log import log


@dataclass
class Piece:
    rect: QRect      # logical coordinates in the virtual desktop space
    dpr: float       # devicePixelRatio of that screen
    pixmap: QPixmap  # device-pixel content


@dataclass
class ScreenShot:
    virtual_rect: QRect
    pieces: list[Piece]

    # ------------------------------------------------------------- display
    def local_rect(self, piece: Piece) -> QRect:
        return piece.rect.translated(-self.virtual_rect.topLeft())

    def composite(self) -> QImage:
        """Logical-size composite of every screen (used by the overlay preview)."""
        img = QImage(self.virtual_rect.size(), QImage.Format.Format_RGB32)
        img.fill(0xFF000000)
        p = QPainter(img)
        for piece in self.pieces:
            p.drawImage(self.local_rect(piece), piece.pixmap.toImage())
        p.end()
        return img

    # ------------------------------------------------------------- crop
    def crop(self, sel: QRect) -> QImage:
        """Crop the selection at native device resolution."""
        sel = sel.normalized()
        parts: list[tuple[QRect, float, QPixmap]] = []
        for piece in self.pieces:
            inter = piece.rect.intersected(sel)
            if inter.isEmpty() or inter.width() < 1 or inter.height() < 1:
                continue
            rel = inter.translated(-piece.rect.topLeft())
            dpr = piece.dpr or 1.0
            dr = QRect(
                round(rel.x() * dpr),
                round(rel.y() * dpr),
                max(1, round(rel.width() * dpr)),
                max(1, round(rel.height() * dpr)),
            )
            parts.append((inter, dpr, piece.pixmap.copy(dr)))

        if not parts:
            raise ValueError("selection outside all screens")

        if len(parts) == 1:
            img = parts[0][2].toImage()
            img.setDevicePixelRatio(1.0)
            return img

        max_dpr = max(p[1] for p in parts)
        canvas = QImage(
            max(1, round(sel.width() * max_dpr)),
            max(1, round(sel.height() * max_dpr)),
            QImage.Format.Format_RGB32,
        )
        canvas.fill(0xFF000000)
        painter = QPainter(canvas)
        for inter, _dpr, pm in parts:
            target = QRect(
                round((inter.x() - sel.x()) * max_dpr),
                round((inter.y() - sel.y()) * max_dpr),
                max(1, round(inter.width() * max_dpr)),
                max(1, round(inter.height() * max_dpr)),
            )
            painter.drawImage(target, pm.toImage())
        painter.end()
        return canvas


def grab_all() -> ScreenShot:
    """Grab every screen at native resolution."""
    pieces: list[Piece] = []
    for screen in QGuiApplication.screens():
        pm = screen.grabWindow(0)
        if pm.isNull():
            log.warning("grabWindow returned null for screen %s", screen.name())
            continue
        pieces.append(Piece(rect=screen.geometry(), dpr=float(screen.devicePixelRatio() or 1.0), pixmap=pm))
    if not pieces:
        raise RuntimeError("could not capture any screen")
    vr = pieces[0].rect
    for p in pieces[1:]:
        vr = vr.united(p.rect)
    return ScreenShot(virtual_rect=vr, pieces=pieces)


def grab_region(rect: QRect) -> QImage:
    """One-shot region grab (logical coordinates) — used by CLI capture."""
    return grab_all().crop(rect)


def png_bytes(image: QImage) -> bytes:
    # keep the QByteArray alive — a temporary here lets Qt write into freed memory
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(ba)
