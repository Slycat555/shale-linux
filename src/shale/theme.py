"""Shared look for Shale's own apps (installer, updater): flat, following the KDE colour scheme."""

import configparser
import os

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory


def _kde_colors():
    """The user's KDE colour scheme (Shale Dark, Shale Darker, light or custom) from kdeglobals."""
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str
    home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    try:
        # Later files win: system defaults, then the global theme's defaults (Plasma keeps
        # those in kdedefaults), then the user's own settings.
        cfg.read(["/etc/xdg/kdeglobals", os.path.join(home, "kdedefaults", "kdeglobals"),
                  os.path.join(home, "kdeglobals")], encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError):
        pass

    def get(group, key, default):
        try:
            r, g, b = (int(v) for v in cfg.get(group, key).split(",")[:3])
            return QColor(r, g, b)
        except (configparser.Error, ValueError):
            return QColor(default)

    return {
        "bg": get("Colors:Window", "BackgroundNormal", "#1e1e1e"),
        "text": get("Colors:Window", "ForegroundNormal", "#ececec"),
        "muted": get("Colors:Window", "ForegroundInactive", "#9a9a9a"),
        "accent": get("Colors:Selection", "BackgroundNormal", "#3584e4"),
        "accent_text": get("Colors:Selection", "ForegroundNormal", "#ffffff"),
        "danger": get("Colors:Window", "ForegroundNegative", "#e5534b"),
    }


_c = _kde_colors()
DARK = _c["bg"].lightnessF() < 0.5


def _step(n):
    """The window colour n steps away from it: lighter on dark schemes, darker on light ones."""
    bg = _c["bg"]
    d = n if DARK else -n
    return QColor(*(max(0, min(255, v + d)) for v in (bg.red(), bg.green(), bg.blue()))).name()


def _mix(a, b, amount):
    return QColor(*(round(x + (y - x) * amount) for x, y in
                    ((a.red(), b.red()), (a.green(), b.green()), (a.blue(), b.blue())))).name()


BG = _c["bg"].name()
SURFACE = _step(8)
SURFACE_HOVER = _step(16)
BORDER = _step(24)
SCROLL_HANDLE = _step(38)
INDICATOR_BORDER = _step(60)
LOG_BG = _step(-8)
TEXT = _c["text"].name()
MUTED = _c["muted"].name()
DISABLED = _mix(_c["bg"], _c["text"], 0.3)
PLACEHOLDER = _mix(_c["bg"], _c["text"], 0.4)
LOG_TEXT = _mix(_c["bg"], _c["text"], 0.75)
ACCENT = _c["accent"].name()
ACCENT_TEXT = _c["accent_text"].name()
ACCENT_HOVER = _mix(_c["accent"], QColor("white"), 0.1)
ACCENT_DISABLED = _mix(_c["bg"], _c["accent"], 0.35)
ACCENT_DISABLED_TEXT = _mix(_c["bg"], _c["text"], 0.55)
DANGER = _c["danger"].name()

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
QPushButton:disabled {{ color: {DISABLED}; }}
QPushButton[role="primary"] {{
    background: {ACCENT}; border: none; color: {ACCENT_TEXT}; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:disabled {{ background: {ACCENT_DISABLED}; color: {ACCENT_DISABLED_TEXT}; }}
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
QListWidget::item:selected {{ background: {ACCENT}; color: {ACCENT_TEXT}; }}

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
    width: 16px; height: 16px; border-radius: 9px; border: 1px solid {INDICATOR_BORDER};
    background: {SURFACE};
}}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {ACCENT_TEXT}, stop:0.35 {ACCENT_TEXT}, stop:0.45 {ACCENT}, stop:1 {ACCENT});
    border: 1px solid {ACCENT};
}}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid {INDICATOR_BORDER};
    background: {SURFACE};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}

QProgressBar {{
    background: {SURFACE}; border: none; border-radius: 4px; height: 8px;
    max-height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QPlainTextEdit {{
    background: {LOG_BG}; border: 1px solid {BORDER}; border-radius: 8px;
    color: {LOG_TEXT}; font-family: monospace; font-size: 9pt;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {SCROLL_HANDLE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; }}
QMessageBox QLabel {{ font-size: 11pt; }}
"""


def apply(app: QApplication):
    from PySide6.QtGui import QIcon
    if "/usr/share/icons" not in QIcon.themeSearchPaths():
        QIcon.setThemeSearchPaths(QIcon.themeSearchPaths() + ["/usr/share/icons"])
    if QIcon.themeName() in ("", "hicolor"):
        QIcon.setThemeName("breeze-dark" if DARK else "breeze")
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.Base, SURFACE), (QPalette.AlternateBase, BG),
        (QPalette.Button, SURFACE), (QPalette.Text, TEXT), (QPalette.WindowText, TEXT),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT),
        (QPalette.HighlightedText, ACCENT_TEXT), (QPalette.PlaceholderText, PLACEHOLDER),
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
