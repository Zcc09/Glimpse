"""Dark theme: blue + teal on near-black, matching the SyncPlayer icon family."""
from __future__ import annotations

BG = "#0f1418"
PANEL = "#151c21"
PANEL2 = "#101a1f"
BORDER = "#223038"
BORDER2 = "#2a3a42"
TEXT = "#e8eef2"
MUTED = "#93a4ae"
BLUE = "#2d7ff9"
BLUE_HI = "#3f8bff"
TEAL = "#14b8a6"
TEAL_TEXT = "#5eead4"
DANGER = "#f0616d"
WARN = "#f5b83d"
OK = "#34d399"
SEL = "#1d3550"

QSS = f"""
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: "Segoe UI", "Segoe UI Variable", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog, #root {{ background: {BG}; }}

QFrame#card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#h1 {{ font-size: 19px; font-weight: 600; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#chip {{
    background: #14343f; color: {TEAL_TEXT};
    border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
}}
QLabel#chip_blue {{
    background: #12294b; color: #9cc6ff;
    border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
}}
QLabel#error {{ color: {DANGER}; }}

QPushButton {{
    background: #1c262c; border: 1px solid {BORDER2}; border-radius: 8px;
    padding: 6px 12px; color: #dbe6ec;
}}
QPushButton:hover {{ background: #22303a; border-color: #37505c; }}
QPushButton:pressed {{ background: #182228; }}
QPushButton:disabled {{ color: #5b6b74; border-color: #1c262c; }}
QPushButton#primary {{ background: {BLUE}; border-color: {BLUE}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {BLUE_HI}; }}
QPushButton#danger:hover {{ background: #3a1e22; border-color: {DANGER}; color: #ffd7da; }}
QPushButton#link {{ background: transparent; border: none; color: {BLUE_HI}; padding: 2px 4px; }}
QPushButton#link:hover {{ color: #8bb8ff; text-decoration: underline; }}

QPlainTextEdit, QTextEdit, QLineEdit, QSpinBox, QComboBox {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 7px;
    selection-background-color: {BLUE};
}}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {BLUE}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL}; border: 1px solid {BORDER2}; selection-background-color: {SEL};
    outline: none; padding: 2px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; background: #1c262c; border: none; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER2}; background: {PANEL2}; }}
QCheckBox::indicator:checked {{ background: {BLUE}; border-color: {BLUE}; }}

QListWidget {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 8px; outline: none; }}
QListWidget::item {{ padding: 7px 8px; border-radius: 7px; margin: 2px; }}
QListWidget::item:hover {{ background: #1a242b; }}
QListWidget::item:selected {{ background: {SEL}; color: white; }}

QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {TEAL_TEXT}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c3b44; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4d58; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2c3b44; border-radius: 5px; min-width: 30px; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: {PANEL}; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 7px 13px; margin-right: 3px;
    border: 1px solid transparent; border-radius: 8px; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {TEXT}; background: #1a242b; }}
QTabBar::tab:selected {{ color: white; background: {SEL}; border-color: #2b4a6b; }}

QTreeWidget {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 8px; outline: none; }}
QTreeWidget::item {{ padding: 5px 4px; }}
QTreeWidget::item:hover {{ background: #1a242b; }}
QTreeWidget::item:selected {{ background: {SEL}; color: white; }}
QHeaderView::section {{
    background: {PANEL}; color: {TEAL_TEXT}; border: none; border-bottom: 1px solid {BORDER};
    padding: 5px 7px; font-weight: 600;
}}

QProgressBar {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 7px; height: 14px;
    text-align: center; color: {TEXT}; font-size: 11px;
}}
QProgressBar::chunk {{ background: {BLUE}; border-radius: 6px; }}

QMenu {{ background: #141b20; border: 1px solid {BORDER2}; border-radius: 9px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SEL}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {BLUE}; padding: 4px 6px; }}

QSlider::groove:horizontal {{ height: 4px; background: #26343c; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; background: {BLUE}; }}
"""


def apply(app) -> None:
    from PySide6.QtGui import QFont

    app.setStyle("Fusion")
    font = QFont("Segoe UI")
    font.setPointSizeF(9.5)
    app.setFont(font)
    app.setStyleSheet(QSS)
