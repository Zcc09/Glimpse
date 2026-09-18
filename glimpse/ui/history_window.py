"""History browser: every capture, text, translation, search and song ID."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import icons, util
from . import theme as T

KIND_META = {
    "text": ("TEXT", "text"),
    "translate": ("TRANSLATE", "translate"),
    "search": ("VISUAL", "search"),
    "qr": ("CODE", "qr"),
    "audio": ("SONG", "music"),
    "copy": ("IMAGE", "image"),
}


class HistoryWindow(QWidget):
    def __init__(self, controller, history):
        super().__init__(None)
        self.controller = controller
        self.history = history
        self.entries: list[dict] = []

        self.setWindowTitle("Glimpse — History")
        self.setWindowIcon(icons.app_icon())
        self.resize(1040, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("History")
        title.setObjectName("h1")
        top.addWidget(title)
        top.addSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search text…")
        self.search.setFixedWidth(240)
        self.search.returnPressed.connect(self.reload)
        self.search.textChanged.connect(lambda _t: self.reload())
        top.addWidget(self.search)
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("All kinds", "")
        self.kind_filter.addItem("Text", "text")
        self.kind_filter.addItem("Translate", "translate")
        self.kind_filter.addItem("Visual search", "search")
        self.kind_filter.addItem("Codes", "qr")
        self.kind_filter.addItem("Songs", "audio")
        self.kind_filter.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.kind_filter)
        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        top.addWidget(self.count_label)
        top.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        clear = QPushButton(icons.icon("trash", 18), " Clear all")
        clear.clicked.connect(self._clear_all)
        top.addWidget(clear)
        close_btn = QPushButton(icons.icon("close", 18), "")
        close_btn.clicked.connect(self.close)
        top.addWidget(close_btn)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.list = QListWidget()
        self.list.setMinimumWidth(330)
        self.list.currentRowChanged.connect(self._show_entry)
        splitter.addWidget(self.list)

        detail = QFrame()
        detail.setObjectName("card")
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(14, 12, 14, 12)
        dl.setSpacing(10)

        dhead = QHBoxLayout()
        self.d_chip = QLabel("TEXT")
        self.d_chip.setObjectName("chip_blue")
        dhead.addWidget(self.d_chip)
        self.d_time = QLabel("")
        self.d_time.setObjectName("muted")
        dhead.addWidget(self.d_time)
        dhead.addStretch(1)
        dl.addLayout(dhead)

        dbody = QHBoxLayout()
        self.d_image = QLabel()
        self.d_image.setFixedSize(240, 200)
        self.d_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.d_image.setStyleSheet("background: #101a1f; border: 1px solid #223038; border-radius: 10px;")
        self.d_image.setCursor(Qt.CursorShape.PointingHandCursor)
        self.d_image.mousePressEvent = lambda _e: self._open_image()  # type: ignore[method-assign]
        dbody.addWidget(self.d_image, 0, Qt.AlignmentFlag.AlignTop)
        dv = QVBoxLayout()
        self.d_text = QPlainTextEdit()
        self.d_text.setReadOnly(True)
        self.d_text.setPlaceholderText("(no text)")
        dv.addWidget(self.d_text, 1)
        self.d_extra = QLabel("")
        self.d_extra.setObjectName("muted")
        self.d_extra.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.d_extra.setWordWrap(True)
        dv.addWidget(self.d_extra)
        dbody.addLayout(dv, 1)
        dl.addLayout(dbody, 1)

        drow = QHBoxLayout()
        self.b_copy_text = QPushButton("Copy text")
        self.b_copy_text.setObjectName("primary")
        self.b_copy_text.clicked.connect(lambda: self.controller.copy_text(self.current_text()))
        self.b_copy_img = QPushButton("Copy image")
        self.b_copy_img.clicked.connect(self._copy_image)
        self.b_open_img = QPushButton("Open image")
        self.b_open_img.clicked.connect(self._open_image)
        self.b_open_link = QPushButton("Open link")
        self.b_open_link.clicked.connect(self._open_link)
        self.b_translate = QPushButton(icons.icon("translate", 18), " Translate")
        self.b_translate.clicked.connect(self._translate_entry)
        self.b_delete = QPushButton(icons.icon("trash", 18), " Delete")
        self.b_delete.clicked.connect(self._delete_entry)
        for b in (self.b_copy_text, self.b_copy_img, self.b_open_img, self.b_open_link, self.b_translate, self.b_delete):
            drow.addWidget(b)
        drow.addStretch(1)
        dl.addLayout(drow)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        root.addWidget(splitter, 1)

        self._entry: dict | None = None
        self._placed = False

    # ---------------------------------------------------------------- data
    def reload(self) -> None:
        kind = self.kind_filter.currentData() or None
        query = self.search.text().strip()
        self.entries = self.history.list_entries(limit=400, kind=kind, query=query)
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.entries:
            label, ikind = KIND_META.get(e["kind"], ("ITEM", "info"))
            snippet = util.shorten(e.get("title") or e.get("text") or "", 60)
            when = time.strftime("%b %d %H:%M", time.localtime(e["ts"]))
            item = QListWidgetItem(icons.icon(ikind, 18), f"{snippet or '(image)'}\n{label}  •  {when}")
            item.setData(Qt.ItemDataRole.UserRole, e["id"])
            self.list.addItem(item)
        self.list.blockSignals(False)
        total = self.history.count()
        self.count_label.setText(f"{len(self.entries)} shown • {total} total")
        if self.entries:
            self.list.setCurrentRow(0)
        else:
            self._entry = None

    def _row_entry(self, row: int) -> dict | None:
        if row < 0 or row >= len(self.entries):
            return None
        return self.entries[row]

    def _show_entry(self, row: int) -> None:
        e = self._row_entry(row)
        self._entry = e
        if not e:
            return
        label, _ = KIND_META.get(e["kind"], ("ITEM", "info"))
        self.d_chip.setText(label)
        self.d_time.setText(time.strftime("%b %d, %Y %H:%M:%S", time.localtime(e["ts"])))
        self.d_text.setPlainText(e.get("text") or "")
        extra = e.get("extra") or {}
        bits = []
        if extra.get("translation"):
            bits.append(f"Translation ({extra.get('target', '?')}): {util.shorten(extra['translation'], 400)}")
        if extra.get("url"):
            bits.append(f"Opened: {extra['url']}")
        if extra.get("detected"):
            bits.append(f"Detected: {extra['detected']} • engine: {extra.get('engine', '?')}")
        if extra.get("artist") or extra.get("song_title"):
            bits.append(f"Song: {extra.get('artist', '')} — {extra.get('song_title', '')}")
        self.d_extra.setText("\n".join(bits))

        img = self.history.load_thumb(e)
        if img is not None:
            pm = QPixmap.fromImage(img)
            self.d_image.setPixmap(pm.scaled(240, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.d_image.setPixmap(icons.glyph_pixmap("image", 48, T.MUTED))

        self.b_copy_text.setEnabled(bool(e.get("text")))
        self.b_copy_img.setEnabled(bool(e.get("image_path")))
        self.b_open_img.setEnabled(bool(e.get("image_path")))
        linkable = bool((e.get("extra") or {}).get("url")) or (e.get("kind") == "qr" and (e.get("text") or "").startswith("http"))
        self.b_open_link.setEnabled(linkable)
        self.b_translate.setEnabled(bool(e.get("text")))

    # ---------------------------------------------------------------- actions
    def current_text(self) -> str:
        return self._entry.get("text") if self._entry else ""

    def _copy_image(self) -> None:
        if not self._entry:
            return
        img = self.history.load_image(self._entry)
        if img is not None:
            util.copy_image(img)
            self.controller.notify("Image copied", "")

    def _open_image(self) -> None:
        if not self._entry:
            return
        path = self._entry.get("image_path")
        if path:
            util.open_path(path)

    def _open_link(self) -> None:
        if not self._entry:
            return
        url = (self._entry.get("extra") or {}).get("url")
        if not url and (self._entry.get("text") or "").startswith("http"):
            url = self._entry["text"]
        if url:
            self.controller.open_url(url)

    def _translate_entry(self) -> None:
        if not self._entry:
            return
        self.controller.translate_text_window(self._entry.get("text") or "", self.history.load_image(self._entry))

    def _delete_entry(self) -> None:
        if not self._entry:
            return
        self.history.delete(self._entry["id"])
        self.reload()

    def _clear_all(self) -> None:
        if not self.history.count():
            return
        res = QMessageBox.question(self, "Clear history", "Delete every history entry and its images?")
        if res == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.reload()

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
        self.reload()
