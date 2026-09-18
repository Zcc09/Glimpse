from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def app():
    """Real-platform QApplication (the tests render text and drive windows)."""
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture()
def glimpse_home(tmp_path, monkeypatch):
    home = tmp_path / "glimpse-home"
    home.mkdir()
    monkeypatch.setenv("GLIMPSE_HOME", str(home))
    return home
