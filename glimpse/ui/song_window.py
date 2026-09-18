"""Song identification result window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import icons, util
from ..audio import SongResult, fetch_cover
from . import theme as T


class SongWindow(QWidget):
    def __init__(self, controller, song: SongResult | None, wav_path: str = "", error: str | None = None):
        super().__init__(None)
        self.controller = controller
        self.song = song
        self.wav_path = wav_path
        self.error = error

        self.setWindowTitle("Glimpse — Song")
        self.setWindowIcon(icons.app_icon())
        self.resize(560, 380)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        header = QHBoxLayout()
        chip = QLabel("SONG")
        chip.setObjectName("chip")
        header.addWidget(chip)
        header.addStretch(1)
        close_btn = QPushButton(icons.icon("close", 18), "")
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)

        cover_card = QLabel()
        cover_card.setFixedSize(184, 184)
        cover_card.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_card.setStyleSheet("background: #101a1f; border: 1px solid #223038; border-radius: 14px;")
        cover_card.setPixmap(icons.glyph_pixmap("music", 72, T.MUTED))
        self.cover_card = cover_card
        body.addWidget(cover_card, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(6)

        if song:
            title = QLabel(song.title)
            title.setObjectName("h1")
            title.setWordWrap(True)
            info.addWidget(title)
            artist = QLabel(song.artist or "Unknown artist")
            artist.setObjectName("h2")
            artist.setStyleSheet(f"color: {T.TEAL_TEXT};")
            artist.setWordWrap(True)
            info.addWidget(artist)
            if song.genre:
                g = QLabel(song.genre)
                g.setObjectName("muted")
                info.addWidget(g)

            row = QHBoxLayout()
            if song.youtube_url:
                b = QPushButton(icons.icon("play", 18), " Play on YouTube")
                b.setObjectName("primary")
                b.clicked.connect(lambda: self.controller and self.controller.open_url(song.youtube_url))
                row.addWidget(b)
            if song.shazam_url:
                b = QPushButton("Shazam page")
                b.clicked.connect(lambda: self.controller and self.controller.open_url(song.shazam_url))
                row.addWidget(b)
            if song.apple_url:
                b = QPushButton("Apple Music")
                b.clicked.connect(lambda: self.controller and self.controller.open_url(song.apple_url))
                row.addWidget(b)
            row.addStretch(1)
            info.addLayout(row)

            row2 = QHBoxLayout()
            copy_btn = QPushButton(icons.icon("copy", 18), " Copy “artist — title”")
            copy_btn.clicked.connect(self._copy)
            row2.addWidget(copy_btn)
            if song.youtube_url:
                yt_btn = QPushButton(icons.icon("search", 18), " Search on YouTube")
                yt_btn.clicked.connect(self._search_youtube)
                row2.addWidget(yt_btn)
            row2.addStretch(1)
            info.addLayout(row2)
        else:
            headline = QLabel("Couldn't identify a song")
            headline.setObjectName("h1")
            info.addWidget(headline)
            msg = QLabel(
                self.error
                or "Nothing matched. Make sure the song is playing through your default output "
                "device (or switch Glimpse to Microphone in Settings) and try again with a longer listen."
            )
            msg.setWordWrap(True)
            msg.setObjectName("muted")
            info.addWidget(msg)

        info.addStretch(1)

        row3 = QHBoxLayout()
        again = QPushButton(icons.icon("music", 18), " Listen again")
        again.clicked.connect(lambda: self.controller and self.controller.identify_song())
        row3.addWidget(again)
        if self.wav_path:
            open_btn = QPushButton("Open recording")
            open_btn.setToolTip(self.wav_path)
            open_btn.clicked.connect(lambda: util.open_path(self.wav_path))
            row3.addWidget(open_btn)
        row3.addStretch(1)
        info.addLayout(row3)

        body.addLayout(info, 1)
        root.addLayout(body, 1)

        if song and song.cover_url:
            self._load_cover(song.cover_url)

        self._placed = False

    # ---------------------------------------------------------------- helpers
    def _load_cover(self, url: str) -> None:
        if self.controller:
            self.controller.fetch_cover_into(self, url)
        else:
            from ..util import run_bg

            run_bg(lambda: fetch_cover(url), on_ok=self.set_cover)

    def set_cover(self, data: bytes) -> None:
        if not data:
            return
        pm = QPixmap()
        if pm.loadFromData(data):
            self.cover_card.setPixmap(pm.scaled(184, 184, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _copy(self) -> None:
        text = f"{self.song.artist} — {self.song.title}" if self.song and self.song.artist else (self.song.title if self.song else "")
        if text and self.controller:
            self.controller.copy_text(text)

    def _search_youtube(self) -> None:
        from urllib.parse import quote_plus

        q = f"{self.song.artist} {self.song.title}".strip() if self.song else ""
        if q and self.controller:
            self.controller.open_url("https://www.youtube.com/results?search_query=" + quote_plus(q))

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
                    avail.top() + max(12, (avail.height() - self.height()) // 3),
                )
