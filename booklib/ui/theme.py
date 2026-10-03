"""
theme.py – Modern Light / Dark / System theme management with curated color palettes,
professional typography, and bespoke component styling.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

# ── Badge / accent colors for status badges ───────────────────────────────────
BADGE_COLORS = {
    "want":    {"light": "#475569", "dark": "#64748b"},   # Slate neutral instead of blue
    "reading": {"light": "#d97706", "dark": "#f59e0b"},   # warm amber
    "read":    {"light": "#059669", "dark": "#10b981"},   # emerald green
}

THEME_KEY = "theme"  # QSettings key

_JAINI_FONT_FAMILY: str | None = None


def load_jaini_font() -> str:
    """Load and return the Jaini font family name from bundled resources."""
    global _JAINI_FONT_FAMILY
    if _JAINI_FONT_FAMILY:
        return _JAINI_FONT_FAMILY
    font_path = Path(__file__).parent.parent / "resources" / "fonts" / "Jaini-Regular.ttf"
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id >= 0:
            fams = QFontDatabase.applicationFontFamilies(font_id)
            if fams:
                _JAINI_FONT_FAMILY = fams[0]
                return _JAINI_FONT_FAMILY
    _JAINI_FONT_FAMILY = "Jaini"
    return _JAINI_FONT_FAMILY


def get_application_font() -> QFont:
    """Return the primary application font with a modern, high-legibility sans-serif stack."""
    font = QFont()
    font.setFamilies([
        "Segoe UI Variable Text",  # Windows 11 Fluent Design
        "Segoe UI",                # Windows 10
        "Inter",                   # Modern cross-platform standard
        "-apple-system",           # macOS San Francisco
        "SF Pro Text",             # macOS
        "Roboto",                  # ChromeOS / Android / Material
        "Ubuntu",                  # Ubuntu Linux
        "Helvetica Neue",
        "Arial",
        "sans-serif",
    ])
    font.setPointSize(10)
    font.setStyleHint(QFont.SansSerif)
    font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
    return font


def _dark_palette() -> QPalette:
    """
    Curated modern dark theme based on zinc/slate design tokens.
    Deep neutral surfaces with crystal clear contrast.
    """
    p = QPalette()
    # Backgrounds & surfaces
    p.setColor(QPalette.Window,          QColor("#131418"))   # Deep neutral charcoal
    p.setColor(QPalette.Base,            QColor("#17181e"))   # Crisp dark surface for lists/inputs/tables
    p.setColor(QPalette.AlternateBase,   QColor("#1f2129"))   # Elevated card / secondary surface
    p.setColor(QPalette.Button,          QColor("#1f2129"))   # Button background
    p.setColor(QPalette.ToolTipBase,     QColor("#1f2129"))

    # Typography
    p.setColor(QPalette.WindowText,      QColor("#f3f4f6"))   # Off-white primary text
    p.setColor(QPalette.Text,            QColor("#f3f4f6"))
    p.setColor(QPalette.ButtonText,      QColor("#f3f4f6"))
    p.setColor(QPalette.BrightText,      QColor("#ffffff"))
    p.setColor(QPalette.ToolTipText,     QColor("#f3f4f6"))
    p.setColor(QPalette.PlaceholderText, QColor("#717888"))   # Muted placeholder text

    # Highlights & Accents - High-contrast elevated slate without blue fill
    p.setColor(QPalette.Highlight,       QColor("#2e3444"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Link,            QColor("#cbd5e1"))
    p.setColor(QPalette.LinkVisited,     QColor("#94a3b8"))

    # Borders & Dividers
    p.setColor(QPalette.Mid,             QColor("#2e323d"))   # Subtle 1px borders
    p.setColor(QPalette.Midlight,        QColor("#242731"))   # Soft card outlines
    p.setColor(QPalette.Dark,            QColor("#0d0e12"))
    p.setColor(QPalette.Shadow,          QColor("#000000"))

    # Disabled states
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#525866"))
    p.setColor(QPalette.Disabled, QPalette.Text,       QColor("#525866"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#4b5563"))
    p.setColor(QPalette.Disabled, QPalette.Base,       QColor("#131418"))
    p.setColor(QPalette.Disabled, QPalette.Button,     QColor("#17181e"))
    return p


def _light_palette() -> QPalette:
    """
    Curated modern light theme with soft slate-50 backgrounds and crisp slate-900 typography.
    """
    p = QPalette()
    # Backgrounds & surfaces
    p.setColor(QPalette.Window,          QColor("#f8fafc"))   # Slate-50 soft background
    p.setColor(QPalette.Base,            QColor("#ffffff"))   # Pure white surface
    p.setColor(QPalette.AlternateBase,   QColor("#f1f5f9"))   # Slate-100 elevated card surface
    p.setColor(QPalette.Button,          QColor("#f1f5f9"))   # Button background
    p.setColor(QPalette.ToolTipBase,     QColor("#ffffff"))

    # Typography
    p.setColor(QPalette.WindowText,      QColor("#0f172a"))   # Slate-900 sharp text
    p.setColor(QPalette.Text,            QColor("#0f172a"))
    p.setColor(QPalette.ButtonText,      QColor("#0f172a"))
    p.setColor(QPalette.BrightText,      QColor("#000000"))
    p.setColor(QPalette.ToolTipText,     QColor("#0f172a"))
    p.setColor(QPalette.PlaceholderText, QColor("#94a3b8"))   # Slate-400 placeholder

    # Highlights & Accents
    p.setColor(QPalette.Highlight,       QColor("#e2e8f0"))
    p.setColor(QPalette.HighlightedText, QColor("#0f172a"))
    p.setColor(QPalette.Link,            QColor("#2563eb"))
    p.setColor(QPalette.LinkVisited,     QColor("#6366f1"))
    p.setColor(QPalette.Link,            QColor("#2563eb"))
    p.setColor(QPalette.LinkVisited,     QColor("#6366f1"))

    # Borders & Dividers
    p.setColor(QPalette.Mid,             QColor("#cbd5e1"))   # Slate-300 borders
    p.setColor(QPalette.Midlight,        QColor("#e2e8f0"))   # Slate-200 card outlines
    p.setColor(QPalette.Dark,            QColor("#64748b"))
    p.setColor(QPalette.Shadow,          QColor("#94a3b8"))

    # Disabled states
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#94a3b8"))
    p.setColor(QPalette.Disabled, QPalette.Text,       QColor("#94a3b8"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#94a3b8"))
    p.setColor(QPalette.Disabled, QPalette.Base,       QColor("#f8fafc"))
    p.setColor(QPalette.Disabled, QPalette.Button,     QColor("#e2e8f0"))
    return p


def get_theme_stylesheet(dark: bool) -> str:
    """Return a modern, polished Qt stylesheet giving the UI a sleek, contemporary desktop feel."""
    if dark:
        border_color = "#2e323d"
        border_hover = "#434858"
        btn_bg = "#1f2129"
        btn_hover = "#282b35"
        btn_pressed = "#18191f"
        input_bg = "#17181e"
        input_focus = "#cbd5e1"
        menu_bg = "#1b1c23"
        tab_bg = "#17181e"
        scroll_thumb = "rgba(160, 165, 180, 0.28)"
        scroll_thumb_hover = "rgba(160, 165, 180, 0.48)"
        selection_bg = "#2e3444"
        selection_color = "#ffffff"
        selection_border = "#94a3b8"
        header_bg = "#1b1c23"
    else:
        border_color = "#cbd5e1"
        border_hover = "#94a3b8"
        btn_bg = "#f1f5f9"
        btn_hover = "#e2e8f0"
        btn_pressed = "#cbd5e1"
        input_bg = "#ffffff"
        input_focus = "#0f172a"
        menu_bg = "#ffffff"
        tab_bg = "#f8fafc"
        scroll_thumb = "rgba(100, 116, 139, 0.28)"
        scroll_thumb_hover = "rgba(100, 116, 139, 0.50)"
        selection_bg = "#e2e8f0"
        selection_color = "#0f172a"
        selection_border = "#475569"
        header_bg = "#f1f5f9"

    devanagari_brand = "#e07a5f" if dark else "#b84e26"

    return f"""
    /* ── Devanagari App Name & Branding ─────────────────────────────────── */
    QLabel#appNameDevanagari, QLabel#aboutAppDevanagari {{
        color: {devanagari_brand};
        font-family: 'Jaini', sans-serif;
        font-weight: 600;
    }}

    /* ── Dialogs, Popups & Message Boxes ─────────────────────────────────── */
    QDialog, QMessageBox {{
        background-color: palette(window);
        border-radius: 12px;
    }}

    /* ── Main Window & Toolbars ─────────────────────────────────────────── */
    QDialog {{
        background-color: palette(window);
        border-radius: 10px;
    }}
    QMainWindow {{
        background-color: palette(window);
    }}
    QToolBar {{
        border: none;
        border-bottom: 1px solid {border_color};
        background-color: palette(window);
        padding: 4px 8px;
        spacing: 6px;
    }}
    QToolBar::separator {{
        width: 1px;
        background-color: {border_color};
        margin: 4px 6px;
    }}

    /* ── Buttons (PushButtons & ToolButtons) ────────────────────────────── */
    QPushButton {{
        background-color: {btn_bg};
        color: palette(window-text);
        border: 1px solid {border_color};
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 12px;
        font-weight: 500;
        min-height: 20px;
    }}
    QPushButton:hover {{
        background-color: {btn_hover};
        border-color: {border_hover};
    }}
    QPushButton:pressed {{
        background-color: {btn_pressed};
    }}
    QPushButton:disabled {{
        background-color: transparent;
        color: palette(disabled, window-text);
        border-color: transparent;
    }}
    QPushButton:checked {{
        background-color: {selection_bg};
        color: {selection_color};
        border: 1px solid {selection_border};
        font-weight: 600;
    }}

    QToolButton {{
        background-color: transparent;
        color: palette(window-text);
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
        font-weight: 500;
    }}
    QToolButton:hover {{
        background-color: {btn_hover};
        border-color: {border_color};
    }}
    QToolButton:pressed {{
        background-color: {btn_pressed};
    }}
    QToolButton:checked {{
        background-color: {selection_bg};
        color: {selection_color};
        border: 1px solid {selection_border};
        font-weight: 600;
    }}

    /* ── Inputs & Edits ─────────────────────────────────────────────────── */
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {input_bg};
        color: palette(text);
        border: 1px solid {border_color};
        border-radius: 6px;
        padding: 5px 9px;
        font-size: 12px;
        selection-background-color: {selection_bg};
        selection-color: {selection_color};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {input_focus};
    }}

    /* ── Comboboxes ─────────────────────────────────────────────────────── */
    QComboBox {{
        background-color: {input_bg};
        color: palette(text);
        border: 1px solid {border_color};
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        min-height: 20px;
    }}
    QComboBox:hover {{
        border-color: {border_hover};
    }}
    QComboBox:focus {{
        border: 1px solid {input_focus};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 18px;
        border-left: none;
    }}
    QComboBox QAbstractItemView {{
        background-color: {menu_bg};
        color: palette(text);
        border: 1px solid {border_color};
        border-radius: 10px;
        padding: 4px;
        selection-background-color: {selection_bg};
        selection-color: {selection_color};
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        border-radius: 6px;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {selection_bg};
        color: {selection_color};
        border-radius: 6px;
    }}

    /* ── Menus & MenuBar ────────────────────────────────────────────────── */
    QMenuBar {{
        background-color: palette(window);
        border-bottom: 1px solid {border_color};
        padding: 2px 4px;
        font-size: 12px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 4px 8px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background-color: {btn_hover};
    }}
    QMenu {{
        background-color: {menu_bg};
        color: palette(text);
        border: 1px solid {border_color};
        border-radius: 10px;
        padding: 5px;
        font-size: 12px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background-color: {selection_bg};
        color: {selection_color};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {border_color};
        margin: 4px 6px;
    }}

    /* ── Tab Widgets & Tab Bars ─────────────────────────────────────────── */
    QTabWidget::pane {{
        border: 1px solid {border_color};
        border-radius: 6px;
        background-color: palette(base);
    }}
    QTabBar::tab {{
        background-color: {tab_bg};
        color: palette(window-text);
        border: 1px solid {border_color};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 500;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: palette(base);
        color: palette(window-text);
        font-weight: 600;
        border-bottom: 2px solid {selection_border};
    }}
    QTabBar::tab:!selected:hover {{
        background-color: {btn_hover};
    }}

    /* ── Tables & Views ─────────────────────────────────────────────────── */
    QTableView, QListView, QTreeView {{
        background-color: palette(base);
        color: palette(text);
        border: 1px solid {border_color};
        border-radius: 6px;
        outline: none;
        selection-background-color: {selection_bg};
        selection-color: {selection_color};
    }}
    QTableView::item:selected, QListView::item:selected, QTreeView::item:selected {{
        background-color: {selection_bg};
        color: {selection_color};
    }}
    QHeaderView::section {{
        background-color: {header_bg};
        color: palette(window-text);
        border: none;
        border-right: 1px solid {border_color};
        border-bottom: 1px solid {border_color};
        padding: 6px 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QHeaderView::section:last {{
        border-right: none;
    }}

    /* ── Minimalist Modern Scrollbars ────────────────────────────────────── */
    QScrollBar:vertical {{
        background-color: transparent;
        width: 8px;
        margin: 2px 0 2px 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {scroll_thumb};
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {scroll_thumb_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background-color: transparent;
        height: 8px;
        margin: 0 2px 0 2px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {scroll_thumb};
        min-width: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {scroll_thumb_hover};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* ── Status Bar ─────────────────────────────────────────────────────── */
    QStatusBar {{
        border-top: 1px solid {border_color};
        background-color: palette(window);
        color: palette(window-text);
        font-size: 11px;
    }}
    QStatusBar QLabel {{
        color: palette(window-text);
    }}

    /* ── Splitters ──────────────────────────────────────────────────────── */
    QSplitter::handle {{
        background-color: {border_color};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}

    /* ── Tooltips ───────────────────────────────────────────────────────── */
    QToolTip {{
        background-color: {menu_bg};
        color: palette(window-text);
        border: 1px solid {border_color};
        border-radius: 8px;
        padding: 5px 9px;
        font-size: 11px;
    }}
    """


def apply_theme(theme: str) -> None:
    """Apply 'light', 'dark', or 'system' theme to the running QApplication."""
    app = QApplication.instance()
    if not app:
        return
    app.setStyle("Fusion")

    if theme == "system":
        try:
            scheme = app.styleHints().colorScheme()
            use_dark = (scheme == Qt.ColorScheme.Dark)
        except AttributeError:
            use_dark = False
        palette = _dark_palette() if use_dark else _light_palette()
        dark = use_dark
    elif theme == "dark":
        palette = _dark_palette()
        dark = True
    else:
        palette = _light_palette()
        dark = False

    app.setPalette(palette)
    app.setFont(get_application_font())
    app.setStyleSheet(get_theme_stylesheet(dark))


def is_dark(app: QApplication | None = None) -> bool:
    """Return True if the current palette is dark-ish."""
    app = app or QApplication.instance()
    if not app:
        return True
    bg = app.palette().color(QPalette.Window)
    return bg.lightness() < 128


def badge_color(status: str | None) -> QColor:
    """Return the QColor for a status badge in the current theme."""
    if not status or status not in BADGE_COLORS:
        return QColor(0, 0, 0, 0)
    variant = "dark" if is_dark() else "light"
    return QColor(BADGE_COLORS[status][variant])


def apply_window_rounding(widget) -> None:
    """
    Apply native rounded circular corners (Windows 11 DWM) to a top-level window/dialog.
    Safe no-op on earlier Windows versions or other operating systems.
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        if hwnd:
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33
            # DWMWCP_ROUND = 2 (round corners ~8-12px)
            pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                33,
                ctypes.byref(pref),
                ctypes.sizeof(pref)
            )
    except Exception:
        pass

