"""Shared look for Shale's own apps (installer, updater): flat, dark, #1e1e1e."""

import os

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

BG = "#1e1e1e"
SURFACE = "#262626"
SURFACE_HOVER = "#2e2e2e"
BORDER = "#363636"
TEXT = "#ececec"
MUTED = "#9a9a9a"
ACCENT = "#3584e4"
ACCENT_HOVER = "#4a92ea"
DANGER = "#e5534b"

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.svg")

QSS = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 11pt; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 22pt; font-weight: 600; }}
QLabel[role="subtitle"] {{ color: {MUTED}; font-size: 11.5pt; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="error"] {{ color: {DANGER}; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 9px 22px; min-height: 20px;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton:disabled {{ color: #5c5c5c; }}
QPushButton[role="primary"] {{
    background: {ACCENT}; border: none; color: white; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:disabled {{ background: #2c3e55; color: #8a9bb0; }}
QPushButton[role="link"] {{
    background: transparent; border: none; color: {MUTED}; padding: 4px 0;
}}
QPushButton[role="link"]:hover {{ color: {TEXT}; }}

QLineEdit, QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 12px; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {ACCENT};
    outline: none; padding: 4px;
}}

QListWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 6px; outline: none;
}}
QListWidget::item {{ padding: 10px 12px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {SURFACE_HOVER}; }}
QListWidget::item:selected {{ background: {ACCENT}; color: white; }}

QFrame[role="card"] {{
    background: {SURFACE}; border: 2px solid {SURFACE}; border-radius: 14px;
}}
QFrame[role="card"]:hover {{ border: 2px solid {BORDER}; background: {SURFACE_HOVER}; }}
QFrame[role="card"][selected="true"] {{ border: 2px solid {ACCENT}; }}
QFrame[role="panel"] {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
}}

QCheckBox, QRadioButton {{ spacing: 10px; background: transparent; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 9px; border: 1px solid #5a5a5a;
    background: {SURFACE};
}}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 white, stop:0.35 white, stop:0.45 {ACCENT}, stop:1 {ACCENT});
    border: 1px solid {ACCENT};
}}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid #555;
    background: {SURFACE};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}

QProgressBar {{
    background: {SURFACE}; border: none; border-radius: 4px; height: 8px;
    max-height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QPlainTextEdit {{
    background: #161616; border: 1px solid {BORDER}; border-radius: 8px;
    color: #b5b5b5; font-family: monospace; font-size: 9pt;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #444; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; }}
QMessageBox QLabel {{ font-size: 11pt; }}
"""


def apply(app: QApplication):
    from PySide6.QtGui import QIcon
    if "/usr/share/icons" not in QIcon.themeSearchPaths():
        QIcon.setThemeSearchPaths(QIcon.themeSearchPaths() + ["/usr/share/icons"])
    if QIcon.themeName() in ("", "hicolor"):
        QIcon.setThemeName("breeze-dark")
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.Base, SURFACE), (QPalette.AlternateBase, BG),
        (QPalette.Button, SURFACE), (QPalette.Text, TEXT), (QPalette.WindowText, TEXT),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT),
        (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#6f6f6f"),
        (QPalette.ToolTipBase, SURFACE), (QPalette.ToolTipText, TEXT),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    font = QFont("Noto Sans")
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(QSS)


def label(text, role=None, wrap=True):
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    if role:
        lbl.setProperty("role", role)
    return lbl


def button(text, role=None):
    from PySide6.QtWidgets import QPushButton
    btn = QPushButton(text)
    if role:
        btn.setProperty("role", role)
    from PySide6.QtCore import Qt
    btn.setCursor(Qt.PointingHandCursor)
    return btn
