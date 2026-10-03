"""
reader.ui package – User interface widgets for built-in reader.
"""
from booklib.reader.ui.page_view import PageView
from booklib.reader.ui.reader_tab import ReaderTab
from booklib.reader.ui.reader_window import ReaderWindow
from booklib.reader.ui.settings_popover import SettingsDialog
from booklib.reader.ui.thumbs_panel import ThumbsPanel
from booklib.reader.ui.toc_panel import TocPanel

__all__ = [
    "PageView",
    "ReaderTab",
    "ReaderWindow",
    "SettingsDialog",
    "ThumbsPanel",
    "TocPanel",
]
