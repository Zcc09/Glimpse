"""Result window: OCR text, translation, and scanned codes for a capture."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import icons, util
from ..config import LANGUAGES
from ..ocr import OcrResult
from ..translate import TranslationOut
from ..visual import gtranslate_url, text_search_url, wolfram_url
from . import theme as T

KIND_META = {
    "text": ("TEXT", "chip_blue"),
    "translate": ("TRANSLATE", "chip"),
    "code": ("CODE", "chip_blue"),
    "search": ("VISUAL", "chip"),
}


class ZoomView(QDialog):
    """Click-to-zoom image preview."""

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Glimpse — image")
        self.resize(880, 620)
        self._image = image
        self._zoom = 1.0
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self._label)
        area.setStyleSheet("QScrollArea { border: 1px solid #223038; border-radius: 10px; background: #0c1114; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(area)
        row = QHBoxLayout()
        hint = QLabel("Scroll to zoom")
        hint.setObjectName("muted")
        row.addWidget(hint)
        row.addStretch(1)
        copy_btn = QPushButton("Copy image")
        copy_btn.clicked.connect(self._copy)
        save_btn = QPushButton("Save as…")
        save_btn.clicked.connect(self._save)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.accept)
        for b in (copy_btn, save_btn, close_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self._render()

    def _render(self) -> None:
        w = max(32, int(self._image.width() * self._zoom))
        h = max(32, int(self._image.height() * self._zoom))
        self._label.setPixmap(QPixmap.fromImage(self._image).scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def wheelEvent(self, e):  # noqa: N802
        delta = e.angleDelta().y()
        self._zoom = max(0.1, min(6.0, self._zoom * (1.15 if delta > 0 else 0.87)))
        self._render()

    def _copy(self) -> None:
        util.copy_image(self._image)

    def _save(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, "Save image", f"glimpse_{time.strftime('%Y%m%d_%H%M%S')}.png", "PNG image (*.png)")
        if path:
            self._image.save(path, "PNG")


class ResultWindow(QWidget):
    """One window per capture: source text, translation, codes."""

    closed = Signal(object)

    def __init__(self, controller, image: QImage, kind: str = "text", title: str = ""):
        super().__init__(None)
        self.controller = controller
        self.image = image
        self.kind = kind
        self.ocr: OcrResult | None = None
        self.translation: TranslationOut | None = None
        self.codes: list[dict] = []

        label, chip_obj = KIND_META.get(kind, KIND_META["text"])
        self.setWindowTitle(f"Glimpse — {label.title()}")
        self.setWindowIcon(icons.app_icon())
        self.resize(940, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ---------------------------------------------------------- header
        header = QHBoxLayout()
        chip = QLabel(label)
        chip.setObjectName(chip_obj)
        header.addWidget(chip)
        self.title_label = QLabel(title or "Captured area")
        self.title_label.setObjectName("h2")
        header.addWidget(self.title_label, 1)

        self.btn_copy_image = QPushButton(icons.icon("copy", 18), " Image")
        self.btn_copy_image.setToolTip("Copy the captured image to the clipboard")
        self.btn_copy_image.clicked.connect(self._copy_image)
        self.btn_save_image = QPushButton(icons.icon("save", 18), " Save")
        self.btn_save_image.setToolTip("Save the captured image as PNG")
        self.btn_save_image.clicked.connect(self._save_image)
        self.btn_open_image = QPushButton(icons.icon("image", 18), "")
        self.btn_open_image.setToolTip("Preview image (click to zoom)")
        self.btn_open_image.clicked.connect(self._zoom_image)
        for b in (self.btn_copy_image, self.btn_save_image, self.btn_open_image):
            header.addWidget(b)
        close_btn = QPushButton(icons.icon("close", 18), "")
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        root.addLayout(header)

        # ---------------------------------------------------------- body
        body = QHBoxLayout()
        body.setSpacing(12)

        preview_card = QFrame()
        preview_card.setObjectName("card")
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(10, 10, 10, 10)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview.setMinimumWidth(280)
        self.preview.mousePressEvent = lambda _e: self._zoom_image()  # type: ignore[method-assign]
        pv.addWidget(self.preview, 1)
        info = QLabel()
        info.setObjectName("muted")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_info = info
        pv.addWidget(info)
        body.addWidget(preview_card, 3)

        right = QVBoxLayout()
        right.setSpacing(10)

        # source text group
        self.text_group = QFrame()
        self.text_group.setObjectName("card")
        tg = QVBoxLayout(self.text_group)
        tg.setContentsMargins(12, 10, 12, 10)
        tg.setSpacing(8)
        th = QHBoxLayout()
        tlabel = QLabel("Text on screen")
        tlabel.setObjectName("h2")
        th.addWidget(tlabel)
        th.addStretch(1)
        self.text_status = QLabel("")
        self.text_status.setObjectName("muted")
        th.addWidget(self.text_status)
        tg.addLayout(th)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Reading text…")
        tg.addWidget(self.text_edit, 1)
        trow = QHBoxLayout()
        self.btn_copy_text = QPushButton("Copy text")
        self.btn_copy_text.setObjectName("primary")
        self.btn_copy_text.clicked.connect(lambda: self.controller and self.controller.copy_text(self.text_edit.toPlainText()))
        self.btn_translate = QPushButton(icons.icon("translate", 18), " Translate")
        self.btn_translate.clicked.connect(self._translate_clicked)
        self.btn_search = QPushButton(icons.icon("search", 18), " Search")
        self.btn_search.setToolTip("Search this text on Google")
        self.btn_search.clicked.connect(lambda: self.controller and self.controller.open_url(text_search_url(self.text_edit.toPlainText())))
        self.btn_solve = QPushButton("Solve")
        self.btn_solve.setToolTip("Open in WolframAlpha")
        self.btn_solve.setVisible(False)
        self.btn_solve.clicked.connect(lambda: self.controller and self.controller.open_url(wolfram_url(self.text_edit.toPlainText())))
        for b in (self.btn_copy_text, self.btn_translate, self.btn_search, self.btn_solve):
            trow.addWidget(b)
        trow.addStretch(1)
        tg.addLayout(trow)
        right.addWidget(self.text_group, 3)

        # translation group
        self.tr_group = QFrame()
        self.tr_group.setObjectName("card")
        self.tr_group.setVisible(False)
        trg = QVBoxLayout(self.tr_group)
        trg.setContentsMargins(12, 10, 12, 10)
        trg.setSpacing(8)
        trh = QHBoxLayout()
        trlabel = QLabel("Translation")
        trlabel.setObjectName("h2")
        trh.addWidget(trlabel)
        trh.addStretch(1)
        self.tr_target = QComboBox()
        for code, name in LANGUAGES.items():
            if code == "auto":
                continue
            self.tr_target.addItem(name, code)
        self.tr_target.setFixedWidth(210)
        self.tr_target.currentIndexChanged.connect(self._target_changed)
        trh.addWidget(self.tr_target)
        self.btn_swap = QPushButton(icons.icon("swap", 18), "")
        self.btn_swap.setToolTip("Translate the translation back")
        self.btn_swap.clicked.connect(self._swap_clicked)
        trh.addWidget(self.btn_swap)
        trg.addLayout(trh)
        self.tr_edit = QPlainTextEdit()
        self.tr_edit.setReadOnly(True)
        self.tr_edit.setPlaceholderText("Waiting for translation…")
        trg.addWidget(self.tr_edit, 1)
        trrow = QHBoxLayout()
        self.btn_copy_tr = QPushButton("Copy translation")
        self.btn_copy_tr.setObjectName("primary")
        self.btn_copy_tr.clicked.connect(lambda: self.controller and self.controller.copy_text(self.tr_edit.toPlainText()))
        self.btn_gtranslate = QPushButton("Open in Google Translate")
        self.btn_gtranslate.clicked.connect(self._open_gtranslate)
        trrow.addWidget(self.btn_copy_tr)
        trrow.addWidget(self.btn_gtranslate)
        trrow.addStretch(1)
        trg.addLayout(trrow)
        right.addWidget(self.tr_group, 3)

        # codes group
        self.code_group = QFrame()
        self.code_group.setObjectName("card")
        self.code_group.setVisible(False)
        cg = QVBoxLayout(self.code_group)
        cg.setContentsMargins(12, 10, 12, 10)
        cg.setSpacing(8)
        clabel = QLabel("Codes found")
        clabel.setObjectName("h2")
        cg.addWidget(clabel)
        self.code_list = QListWidget()
        self.code_list.setMinimumHeight(90)
        cg.addWidget(self.code_list, 1)
        crow = QHBoxLayout()
        self.btn_copy_code = QPushButton("Copy code")
        self.btn_copy_code.setObjectName("primary")
        self.btn_copy_code.clicked.connect(self._copy_code)
        self.btn_open_code = QPushButton("Open link")
        self.btn_open_code.clicked.connect(self._open_code)
        crow.addWidget(self.btn_copy_code)
        crow.addWidget(self.btn_open_code)
        crow.addStretch(1)
        cg.addLayout(crow)
        right.addWidget(self.code_group, 3)

        right.addStretch(0)
        body.addLayout(right, 5)
        root.addLayout(body, 1)

        # ---------------------------------------------------------- status
        status = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("muted")
        status.addWidget(self.status, 1)
        self.engine_note = QLabel("")
        self.engine_note.setObjectName("muted")
        status.addWidget(self.engine_note)
        root.addLayout(status)

        # ---------------------------------------------------------- state
        self._set_preview()
        if kind == "code":
            self.text_group.setVisible(False)
            self.code_group.setVisible(True)
        elif kind == "translate":
            self.tr_group.setVisible(True)
        self._busy = set()

        QShortcut(QKeySequence("Esc"), self, activated=self.close)

    # ---------------------------------------------------------------- preview
    def _set_preview(self) -> None:
        pm = QPixmap.fromImage(self.image)
        scaled = pm.scaled(300, 340, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(scaled)
        self.preview_info.setText(f"{self.image.width()} × {self.image.height()} px")

    def _zoom_image(self) -> None:
        ZoomView(self.image, self).exec()

    def _copy_image(self) -> None:
        util.copy_image(self.image)
        if self.controller:
            self.controller.notify("Image copied", "The captured area is on your clipboard.")

    def _save_image(self) -> None:
        if self.controller:
            self.controller.save_image_dialog(self.image, self)

    # ---------------------------------------------------------------- OCR
    def set_ocr(self, result: OcrResult) -> None:
        self.ocr = result
        self.text_edit.setPlainText(result.text or "")
        n = len([ln for ln in (result.text or "").splitlines() if ln.strip()])
        self.text_status.setText(f"{n} line{'s' if n != 1 else ''} • {result.engine}")
        self.btn_solve.setVisible(util.looks_like_math(result.text or ""))
        if not (result.text or "").strip():
            self.text_status.setText("no text found")
            self.text_edit.setPlaceholderText("No text was found in the selection.")
        self.engine_note.setText(f"OCR: {result.engine} ({result.language})")

    def set_text(self, text: str) -> None:
        """Fill the source text without an OcrResult (e.g. re-opened from history)."""
        self.text_edit.setPlainText(text or "")

    # ---------------------------------------------------------------- translation
    def set_target(self, code: str) -> None:
        idx = self.tr_target.findData(code)
        if idx >= 0:
            self.tr_target.blockSignals(True)
            self.tr_target.setCurrentIndex(idx)
            self.tr_target.blockSignals(False)

    def current_target(self) -> str:
        return self.tr_target.currentData() or "ar"

    def set_translation_busy(self, target: str) -> None:
        self.tr_group.setVisible(True)
        self.set_target(target)
        self.tr_edit.setPlainText("")
        self.tr_edit.setPlaceholderText("Translating…")
        self.status.setText(f"Translating to {LANGUAGES.get(target, target)}…")

    def set_translation(self, out: TranslationOut, target_label: str | None = None) -> None:
        self.translation = out
        self.tr_group.setVisible(True)
        self.set_target(out.target)
        self.tr_edit.setPlainText(out.text)
        self.status.setText("")
        self.engine_note.setText(f"Translate: {out.engine} → {LANGUAGES.get(out.target, out.target)} (source: {out.detected})")

    def _translate_clicked(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            return
        if self.controller:
            self.controller.translate_into(self, text)

    def _target_changed(self) -> None:
        text = self.text_edit.toPlainText().strip() or (self.translation.text if self.translation else "")
        if not text or not self.controller:
            return
        self.controller.translate_into(self, text, target=self.current_target(), user_picked=True)

    def _swap_clicked(self) -> None:
        if not self.translation or not self.controller:
            return
        src = self.translation.detected if self.translation.detected not in ("auto", "") else "en"
        target = "en" if self.translation.target != "en" else "ar"
        self.controller.translate_into(self, self.translation.text, target=target, source=src, user_picked=True)

    def _open_gtranslate(self) -> None:
        text = self.text_edit.toPlainText() or (self.translation.text if self.translation else "")
        target = self.current_target()
        if self.controller and (text or "").strip():
            self.controller.open_url(gtranslate_url(text, target))

    # ---------------------------------------------------------------- codes
    def set_codes(self, codes: list[dict]) -> None:
        self.codes = codes
        self.code_group.setVisible(True)
        self.code_list.clear()
        for c in codes:
            item = QListWidgetItem(f"{c.get('format', 'code')}: {c.get('text', '')}")
            item.setData(Qt.ItemDataRole.UserRole, c.get("text", ""))
            self.code_list.addItem(item)
        if codes:
            self.code_list.setCurrentRow(0)
            self.status.setText(f"{len(codes)} code{'s' if len(codes) != 1 else ''} found")
        else:
            self.status.setText("No code found in the selection.")
            self.code_list.addItem("(none)")

    def _selected_code(self) -> str:
        item = self.code_list.currentItem()
        return (item.data(Qt.ItemDataRole.UserRole) if item else "") or ""

    def _copy_code(self) -> None:
        code = self._selected_code()
        if code and self.controller:
            self.controller.copy_text(code)

    def _open_code(self) -> None:
        code = self._selected_code()
        if not code or not self.controller:
            return
        if code.startswith(("http://", "https://")):
            self.controller.open_url(code)
        else:
            self.controller.copy_text(code)

    # ---------------------------------------------------------------- status/errors
    def set_busy(self, text: str) -> None:
        self.status.setText(text)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_error(self, message: str) -> None:
        self.status.setObjectName("error")
        self.status.setStyleSheet(f"color: {T.DANGER};")
        self.status.setText(message)
        self.engine_note.setText("see glimpse.log for details")

    # ---------------------------------------------------------------- lifecycle
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if not self._placed:
            self._placed = True
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                self.move(
                    avail.left() + max(12, (avail.width() - self.width()) // 2),
                    avail.top() + max(12, (avail.height() - self.height()) // 3),
                )

    _placed = False

    def closeEvent(self, e):  # noqa: N802
        self.closed.emit(self)
        super().closeEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(940, 600)
