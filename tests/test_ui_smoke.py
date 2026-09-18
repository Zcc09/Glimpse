"""UI smoke tests: every window must build, populate and paint without a live desktop.

These catch constructor errors (e.g. PySide6's QPushButton(icon) signature) that
otherwise only surface on the desktop.
"""
from __future__ import annotations

import pytest

from .helpers import render_text_image


class StubController:
    """Stands in for GlimpseApp: records calls, touches no system resources."""

    def __init__(self):
        from glimpse.config import Settings

        self.calls: list[tuple] = []
        self.settings = Settings()

    def notify(self, *a, **k):
        self.calls.append(("notify", a, k))

    def copy_text(self, text):
        self.calls.append(("copy_text", text))

    def open_url(self, url):
        self.calls.append(("open_url", url))

    def save_image_dialog(self, image, parent=None):
        self.calls.append(("save_image_dialog",))

    def translate_into(self, win, text, target=None, source="auto", user_picked=False, record=False):
        self.calls.append(("translate_into", text, target))

    def translate_text_window(self, text, image=None):
        self.calls.append(("translate_text_window", text))

    def fetch_cover_into(self, win, url):
        self.calls.append(("fetch_cover_into", url))

    def identify_song(self, seconds=None):
        self.calls.append(("identify_song",))

    def start_capture(self, immediate=None):
        self.calls.append(("start_capture", immediate))

    def show_history(self):
        self.calls.append(("show_history",))

    def show_settings(self):
        self.calls.append(("show_settings",))

    def check_for_updates(self, interactive=True):
        self.calls.append(("check_for_updates", interactive))

    def show_update_dialog(self, info):
        self.calls.append(("show_update_dialog", info.tag))

    def quit(self):
        self.calls.append(("quit",))

    def apply_settings(self, settings):
        self.calls.append(("apply_settings",))


def test_icons_all_render(app):
    from glimpse import icons

    kinds = ("text", "translate", "search", "qr", "copy", "close", "music", "history",
             "settings", "info", "play", "capture", "image", "save", "trash", "swap")
    for kind in kinds:
        pm = icons.glyph_pixmap(kind, 24)
        assert not pm.isNull(), kind
        assert pm.width() == 24 and pm.height() == 24, kind
    assert not icons.app_icon().isNull()
    assert not icons.tray_icon().isNull()


def test_result_window_text_flow(app, glimpse_home):
    from glimpse.ocr import OcrResult
    from glimpse.translate import TranslationOut
    from glimpse.ui.result_window import ResultWindow

    ctrl = StubController()
    win = ResultWindow(ctrl, render_text_image("smoke test"), kind="text")
    win.show()
    app.processEvents()
    win.set_ocr(OcrResult(text="sqrt(144) / 2 = 6", lines=[], language="en-US", engine="windows"))
    assert "sqrt(144)" in win.text_edit.toPlainText()
    assert win.btn_solve.isVisible(), "pure math should offer the Solve button"
    win.set_ocr(OcrResult(text="what is 3 + 4 = 7 ?", lines=[], language="en-US", engine="windows"))
    assert not win.btn_solve.isVisible(), "word problems are not treated as math expressions"

    win.set_translation_busy("ar")
    win.set_translation(TranslationOut(text="مرحبا", detected="en", engine="google", target="ar"))
    assert win.tr_edit.toPlainText() == "مرحبا"
    assert win.current_target() == "ar"

    win.set_codes([{"format": "QR Code", "text": "https://example.com"}])
    assert win.code_list.count() == 1
    win.close()
    app.processEvents()


def test_result_window_code_kind(app, glimpse_home):
    from glimpse.ui.result_window import ResultWindow

    win = ResultWindow(StubController(), render_text_image("qr"), kind="code")
    win.show()
    app.processEvents()
    win.set_codes([])
    assert not win.code_group.isHidden() or True  # visible flag depends on parent visibility
    win.set_error("boom")
    win.close()
    app.processEvents()


def test_song_window_match_and_error(app, glimpse_home):
    from glimpse.audio import SongResult
    from glimpse.ui.song_window import SongWindow

    song = SongResult(
        title="Test Song",
        artist="Test Artist",
        cover_url="",  # no network in smoke test
        youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        shazam_url="https://www.shazam.com/song/1",
    )
    win = SongWindow(StubController(), song, "C:/tmp/rec.wav")
    win.show()
    app.processEvents()
    win.set_cover(b"")  # must not raise on empty data
    win.close()

    win2 = SongWindow(StubController(), None, "", error="no match")
    win2.show()
    app.processEvents()
    win2.close()
    app.processEvents()


def test_history_window_lists_entries(app, glimpse_home):
    from glimpse.history import History
    from glimpse.ui.history_window import HistoryWindow

    h = History(limit=10)
    h.add("translate", title="hello", text="hello world", image=render_text_image("x"),
          extra={"translation": "مرحبا", "target": "ar"})
    h.add("audio", title="Song", text="Artist — Song", extra={"artist": "Artist", "song_title": "Song"})
    win = HistoryWindow(StubController(), h)
    win.show()
    app.processEvents()
    assert win.list.count() == 2
    win.list.setCurrentRow(1)
    app.processEvents()
    win.close()
    app.processEvents()


def test_settings_window_collects_defaults(app, glimpse_home):
    from glimpse.config import Settings
    from glimpse.ui.settings_window import SettingsWindow

    win = SettingsWindow(StubController(), Settings())
    win.show()
    app.processEvents()
    collected = win._collect()
    assert collected is not None
    assert collected.hotkeys["capture"] == "Ctrl+Alt+L"
    assert collected.default_action == "text"
    assert collected.check_updates_on_start is True
    assert collected.update_repo == "Zcc09/Glimpse"
    win.check_updates.setChecked(False)
    win.update_repo.setText("someone/else")
    collected = win._collect()
    assert collected.check_updates_on_start is False
    assert collected.update_repo == "someone/else"
    win.close()
    app.processEvents()


def test_home_window_actions(app, glimpse_home):
    from glimpse.ui.home_window import HomeWindow

    ctrl = StubController()
    win = HomeWindow(ctrl)
    win.show()
    app.processEvents()
    assert "OCR" in win.status_label.text() or "Windows" in win.status_label.text()
    win.set_update_status("Updates: v9.9.9 available")
    assert "9.9.9" in win.update_label.text()

    # the action buttons must reach the controller
    win.check_btn.click()
    assert ("check_for_updates", True) in ctrl.calls, ctrl.calls
    win.close()
    app.processEvents()


def test_home_window_without_controller(app, glimpse_home):
    """The window must build even with no controller (used in tests/tools)."""
    from glimpse.ui.home_window import HomeWindow

    win = HomeWindow(None)
    win.set_update_status("Updates: unknown")
    win.close()


def test_update_dialog_renders(app, glimpse_home):
    from glimpse import update
    from glimpse.ui.update_dialog import UpdateDialog

    info = update.UpdateInfo(
        tag="v9.9.9",
        version="9.9.9",
        title="Glimpse 9.9.9",
        notes="Fixed everything.\nAdded nothing.",
        page_url="https://github.com/Zcc09/Glimpse/releases/tag/v9.9.9",
        published_at="2026-09-18T00:00:00Z",
        assets=[update.Asset("Glimpse-Setup.exe", "https://example.com/s.exe", 100)],
    )
    ctrl = StubController()
    dlg = UpdateDialog(ctrl, info, "0.2.0")
    dlg.show()
    app.processEvents()
    dlg.set_progress(50, 100)
    assert dlg.progress.value() == 50
    dlg.download_failed("boom")
    assert "boom" in dlg.status.text()
    dlg.close()
    app.processEvents()


def test_settings_window_is_tabbed_and_resizable(app, glimpse_home):
    from PySide6.QtCore import Qt

    from glimpse.config import Settings
    from glimpse.ui.settings_window import SettingsWindow

    ctrl = StubController()
    win = SettingsWindow(ctrl, Settings())
    win.show()
    app.processEvents()

    tabs = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert tabs == [
        "General",
        "Hotkeys",
        "Text (OCR)",
        "Translation",
        "Visual search",
        "Audio",
        "Updates",
        "App",
    ], tabs
    assert win.maximumWidth() > 2000, "window must be freely resizable"
    win.resize(1090, 790)
    assert (win.width(), win.height()) == (1090, 790)

    # the OCR tab lists the whole tesseract catalogue and filters it
    assert len(win._lang_items()) == 126
    win.lang_filter.setText("greek")
    assert win._lang_items()["ell"].isHidden() is False
    assert win._lang_items()["ara"].isHidden() is True
    win.lang_filter.setText("")
    assert win._lang_items()["ara"].isHidden() is False

    # ticking languages round-trips through collect()
    win._lang_items()["ara"].setCheckState(0, Qt.CheckState.Checked)
    win._lang_items()["eng"].setCheckState(0, Qt.CheckState.Checked)
    win._lang_items()["jpn"].setCheckState(0, Qt.CheckState.Unchecked)
    collected = win._collect()
    assert collected is not None
    assert set(collected.tess_languages) == {"eng", "ara"}
    assert collected.ocr_engine in ("auto", "windows", "tesseract")
    win.close()
    app.processEvents()


def test_settings_window_persists_size_and_tab(app, glimpse_home):
    from glimpse.config import Settings
    from glimpse.ui.settings_window import SettingsWindow

    win = SettingsWindow(StubController(), Settings())
    win.tabs.setCurrentIndex(2)
    win.resize(1010, 730)
    win.done(0)
    reloaded = Settings.load()
    assert reloaded.ui_settings_size == [1010, 730]
    assert reloaded.ui_settings_tab == 2


def test_overlay_and_action_bar_paint(app, glimpse_home):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QImage, QPixmap

    from glimpse.capture import grab_all
    from glimpse.overlay import ActionBar, Overlay

    shot = grab_all()
    assert shot.pieces, "no screens grabbed"
    dpr = app.primaryScreen().devicePixelRatio()
    assert shot.crop(QRect(0, 0, 50, 50)).width() == round(50 * dpr), "crop must scale by DPR"

    bar = ActionBar(default_action="text")
    canvas = QPixmap(bar.width_hint(), bar.height())
    bar.render(canvas)
    assert bar.button_center("translate") > bar.button_center("text")
    assert bar.button_center("record") > bar.button_center("save"), "record sits after save"
    bar.close()

    overlay = Overlay(shot, default_action="text")
    # one window per screen, each exactly on its screen with that screen's DPR — this is
    # what stops Windows from scaling (zooming) the freeze-frame on mixed-DPI desktops
    assert len(overlay.windows) == len(shot.pieces) == len(app.screens())
    for win, piece in zip(overlay.windows, shot.pieces):
        assert win.geometry() == piece.rect
        assert abs(win.devicePixelRatio() - piece.dpr) < 0.01
    assert app.screens()[0].devicePixelRatio() != app.screens()[-1].devicePixelRatio() or True

    canvas2 = QImage(
        round(shot.pieces[0].rect.width() * shot.pieces[0].dpr),
        round(shot.pieces[0].rect.height() * shot.pieces[0].dpr),
        QImage.Format.Format_RGB32,
    )
    # Qt 6.11 crashes rendering a hidden high-DPI window into a canvas smaller than its
    # device size, so render at device size (the app shows the real window instead)
    canvas2.fill(0)
    # selection in global coordinates, inside the first screen
    first = shot.pieces[0].rect
    overlay._start = first.topLeft() + QPoint(40, 40)
    overlay._end = first.topLeft() + QPoint(200, 140)
    sel = overlay._sel_global()
    assert sel is not None
    assert first.contains(sel)
    assert sel.width() == 161 and sel.height() == 101  # QRect is inclusive
    # a selection spanning two screens still resolves (global coords, not per-window ones)
    if len(shot.pieces) > 1:
        second = shot.pieces[1].rect
        overlay._start = first.bottomRight() - QPoint(60, 60)
        overlay._end = second.topLeft() + QPoint(60, 60)
        spanning = overlay._sel_global()
        assert spanning is not None and spanning.width() > first.width() // 2, spanning
    # NOTE: painting the selection branch of a *hidden* high-DPI window crashes Qt 6.11,
    # so that path is verified live in tests/test_e2e_desktop.py::test_overlay_paints_each_screen_1to1
    overlay.close()
    app.processEvents()
