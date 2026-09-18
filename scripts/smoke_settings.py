"""Smoke-run the tabbed settings window for real: tabs, filter, download, live OCR test.

Run with GLIMPSE_HOME pointing at a scratch dir so the user's real settings are untouched:
    GLIMPSE_HOME="$LOCALAPPDATA/Temp/glimpse_settings_smoke" .venv/Scripts/python.exe scripts/smoke_settings.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glimpse.config import Settings  # noqa: E402
from glimpse.ui.settings_window import SettingsWindow  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}{' — ' + detail if detail else ''}", flush=True)
    if not ok:
        failures.append(name)


def main() -> int:
    app = QApplication([])
    settings = Settings()
    settings.tess_languages = ["eng"]
    w = SettingsWindow(None, settings)
    w.show()

    tabs = [w.tabs.tabText(i) for i in range(w.tabs.count())]
    check("window has one tab per settings group", len(tabs) >= 7, " / ".join(tabs))
    check("window is resizable", w.minimumSize().width() < 1000 and w.maximumSize().width() > 2000,
          f"min {w.minimumWidth()}x{w.minimumHeight()}, max {w.maximumWidth()}")
    w.resize(1120, 820)
    check("window accepts a larger size", w.width() == 1120 and w.height() == 820)

    items = w._lang_items()
    check("all 126 tesseract languages listed", len(items) == 126, f"{len(items)} listed")

    w.tabs.setCurrentIndex(2)
    check("text tab is the OCR tab", w.tabs.currentIndex() == 2, w.tabs.tabText(2))

    w.lang_filter.setText("arab")
    hidden = [c for c, it in items.items() if it.isHidden()]
    check("filter hides non-matching languages", items["ara"].isHidden() is False and len(hidden) > 100,
          f"{len(hidden)} hidden")
    w.lang_filter.setText("")

    items["eng"].setCheckState(0, Qt.CheckState.Checked)
    items["ara"].setCheckState(0, Qt.CheckState.Checked)
    collected = w._collect()
    check("collect round-trips the ticked languages", collected is not None and set(collected.tess_languages) == {"eng", "ara"},
          str(getattr(collected, "tess_languages", None)))

    state = {"phase": "ocr"}
    w.tabs.setCurrentIndex(2)
    w._test_ocr()

    def poll() -> None:
        if state["phase"] == "ocr":
            txt = w.test_out.text()
            if "reading" in txt:
                QTimer.singleShot(400, poll)
                return
            check("Test OCR returns text through the UI", "1234" in txt, txt.replace("\n", " | "))
            check("Test OCR flags nothing as gibberish for the English sample", "low confidence" not in txt.split("\n")[0],
                  txt.split("\n")[0])
            state["phase"] = "download"
            w._start_download(["ara"])
            QTimer.singleShot(400, poll)
            return
        if w._dl is not None:
            QTimer.singleShot(400, poll)
            return
        from glimpse.ocr import languages as L

        check("download finished without errors", "failed" not in w.lang_status.text(), w.lang_status.text())
        check("downloaded language is on disk", "ara" in L.installed_languages(), str(L.tessdata_dir()))
        statuses = [w._lang_items()["ara"].text(1), w._lang_items()["eng"].text(1)]
        check("language list shows installed status", statuses == ["installed", "installed"], str(statuses))

        # Arabic through the pipeline, from the UI's ticked set
        state["phase"] = "arabic"
        w._test_ocr()

        def poll2() -> None:
            if "reading" in w.test_out.text():
                QTimer.singleShot(400, poll2)
                return
            arabic = [ln for ln in w.test_out.text().split("\n") if ln.startswith("Arabic")]
            check("Arabic sample is read by the tesseract engine",
                  bool(arabic) and "tesseract" in arabic[0] and "ال" in arabic[0],
                  arabic[0] if arabic else "no arabic line")

            final = w._collect()
            w.settings = final
            w.done(0)
            reloaded = Settings.load()
            check("window size and tab persist across runs",
                  reloaded.ui_settings_size == [1120, 820] and reloaded.ui_settings_tab == 2,
                  f"{reloaded.ui_settings_size} tab {reloaded.ui_settings_tab}")
            app.quit()

        QTimer.singleShot(400, poll2)

    QTimer.singleShot(1000, poll)
    app.exec()
    print(f"\n{len(failures)} failure(s)" if failures else "\nall settings-window checks passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
