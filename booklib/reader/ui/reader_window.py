"""
reader/ui/reader_window.py – Multi-tab Built-in Reader Window.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QStyle,
    QTabWidget,
    QToolBar,
)

from booklib.app import get_app_icon
from booklib.reader.backend import DocumentBackend, Locator
from booklib.reader.mupdf_backend import MuPdfBackend
from booklib.reader.ui.password_dialog import PasswordDialog
from booklib.reader.ui.reader_tab import ReaderTab
from booklib.utils.fileops import open_file

logger = logging.getLogger(__name__)


class ReaderWindow(QMainWindow):
    """Primary window for the built-in BookLib reader supporting multiple tabs."""

    book_progress_updated = Signal(int, float)      # book_id, progress_fraction
    reading_position_saved = Signal(int, object)     # book_id, Locator

    def __init__(self, conn_supplier=None, parent=None) -> None:
        super().__init__(parent)
        self._conn_supplier = conn_supplier
        self.setWindowTitle("Ratnodadhi Reader")
        self.resize(1100, 800)
        self.setMinimumSize(600, 450)

        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        # Tab widget
        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self._tabs)

        self._build_toolbar()
        self._setup_shortcuts()

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        tb = QToolBar("Reader Toolbar", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        # Contents / TOC
        self.act_toc = tb.addAction("Contents")
        self.act_toc.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        self.act_toc.setToolTip("Table of Contents (T)")
        self.act_toc.triggered.connect(self._on_toggle_toc)

        # Thumbnails
        self.act_thumbs = tb.addAction("Thumbnails")
        self.act_thumbs.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.act_thumbs.setToolTip("Page Thumbnails")
        self.act_thumbs.triggered.connect(self._on_toggle_thumbnails)

        # Bookmarks
        self.act_bookmark = tb.addAction("Bookmark")
        self.act_bookmark.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.act_bookmark.setToolTip("Bookmark this page (Ctrl+D)")
        self.act_bookmark.triggered.connect(self._on_toggle_bookmark)

        self.act_bookmarks = tb.addAction("List")
        self.act_bookmarks.setIcon(self.style().standardIcon(QStyle.SP_FileDialogInfoView))
        self.act_bookmarks.setToolTip("Bookmarks List (Ctrl+B)")
        self.act_bookmarks.triggered.connect(self._on_toggle_bookmarks_panel)

        # Highlights & Notes
        self.act_notes = tb.addAction("Notes")
        self.act_notes.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        self.act_notes.setToolTip("Highlights & Notes (Ctrl+Shift+B)")
        self.act_notes.triggered.connect(self._on_toggle_notes_panel)

        tb.addSeparator()

        # In-book Search
        self.act_search = tb.addAction("Search")
        self.act_search.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.act_search.setToolTip("Find in book (Ctrl+F)")
        self.act_search.triggered.connect(self._on_search)

        tb.addSeparator()

        # Typography / Layout
        self.act_layout = tb.addAction("Layout")
        self.act_layout.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.act_layout.setToolTip("Font size, margins, and view mode")
        self.act_layout.triggered.connect(self._on_layout)

        # Theme
        self.act_theme = tb.addAction("Theme")
        self.act_theme.setToolTip("Cycle theme (Ctrl+Shift+N)")
        self.act_theme.triggered.connect(self._on_theme)

        tb.addSeparator()

        # Zoom controls
        self.act_zoom_in = tb.addAction("+")
        self.act_zoom_in.setToolTip("Zoom In (Ctrl++)")
        self.act_zoom_in.triggered.connect(self._on_zoom_in)

        self.act_zoom_out = tb.addAction("-")
        self.act_zoom_out.setToolTip("Zoom Out (Ctrl+-)")
        self.act_zoom_out.triggered.connect(self._on_zoom_out)

        self.act_fit_width = tb.addAction("Fit Width")
        self.act_fit_width.setToolTip("Fit to Width (Ctrl+1)")
        self.act_fit_width.triggered.connect(self._on_fit_width)

        self.act_fit_page = tb.addAction("Fit Page")
        self.act_fit_page.setToolTip("Fit to Page (Ctrl+2)")
        self.act_fit_page.triggered.connect(self._on_fit_page)

        tb.addSeparator()

        # External Reader
        self.act_external = tb.addAction("↗ External")
        self.act_external.setToolTip("Open in default system reader")
        self.act_external.triggered.connect(self._on_open_external)

        # Fullscreen
        self.act_fullscreen = tb.addAction("⤢ Fullscreen")
        self.act_fullscreen.setToolTip("Toggle Fullscreen (F11)")
        self.act_fullscreen.triggered.connect(self._on_toggle_fullscreen)

    def _setup_shortcuts(self) -> None:
        """Register reader navigation and manipulation shortcuts."""
        # Paging
        self._add_sc("Right", self._on_next_page)
        self._add_sc("PgDown", self._on_next_page)
        self._add_sc("Space", self._on_next_page)
        self._add_sc("Left", self._on_prev_page)
        self._add_sc("PgUp", self._on_prev_page)
        self._add_sc("Shift+Space", self._on_prev_page)
        self._add_sc("Home", self._on_first_page)
        self._add_sc("End", self._on_last_page)

        # Actions
        self._add_sc("Ctrl+F", self._on_search)
        self._add_sc("F3", self._on_search_next_hit)
        self._add_sc("Shift+F3", self._on_search_prev_hit)
        self._add_sc("Ctrl+G", self._on_goto_page_dialog)
        self._add_sc("Ctrl+W", self._on_close_current_tab)
        self._add_sc("Ctrl+Tab", self._on_next_tab)
        self._add_sc("Ctrl+Shift+N", self._on_theme)
        self._add_sc("F11", self._on_toggle_fullscreen)
        self._add_sc("Esc", self._on_esc)
        self._add_sc("T", self._on_toggle_toc)
        self._add_sc("Ctrl+D", self._on_toggle_bookmark)
        self._add_sc("Ctrl+B", self._on_toggle_bookmarks_panel)
        self._add_sc("Ctrl+Shift+B", self._on_toggle_notes_panel)
        self._add_sc("Ctrl+1", self._on_fit_width)
        self._add_sc("Ctrl+2", self._on_fit_page)
        self._add_sc("Ctrl+Plus", self._on_zoom_in)
        self._add_sc("Ctrl+=", self._on_zoom_in)
        self._add_sc("Ctrl+-", self._on_zoom_out)

    def _add_sc(self, key_str: str, slot) -> None:
        act = QAction(self)
        act.setShortcut(QKeySequence(key_str))
        act.triggered.connect(slot)
        self.addAction(act)

    # ── Document Open & Tab Management ────────────────────────────────────────

    def open_book(
        self,
        path: str,
        book_id: int | None = None,
        locator: Locator | None = None,
        highlight_query: str | None = None,
    ) -> bool:
        """Open a book in a new tab (or focus existing tab)."""
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "File Not Found", f"Cannot find book file:\n{path}")
            return False

        # Check if already open
        for i in range(self._tabs.count()):
            tab: ReaderTab = self._tabs.widget(i)
            if tab.file_path == path:
                self._tabs.setCurrentIndex(i)
                if locator is not None:
                    pno, y = tab.backend.page_for(locator)
                    tab.goto_page(pno, y)
                if highlight_query:
                    tab._search_input.setText(highlight_query)
                    tab._on_search_next()
                return True

        # Open document with backend
        backend = MuPdfBackend()
        opened = backend.open(str(p))

        # Check password prompt if encrypted
        if not opened and backend.is_encrypted:
            dlg = PasswordDialog(p.name, self)
            if dlg.exec():
                pwd = dlg.get_password()
                opened = backend.authenticate(pwd)
            else:
                backend.close()
                return False

        if not opened:
            backend.close()
            # Offer fallback to external reader
            res = QMessageBox.question(
                self,
                "Format Unsupported",
                f"The built-in reader could not open '{p.name}'.\n\nWould you like to open it in your external reader?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if res == QMessageBox.Yes:
                open_file(str(p))
            return False

        # Create tab
        tab = ReaderTab(backend, str(p), book_id=book_id, conn_supplier=self._conn_supplier, parent=self)
        tab.open_external_requested.connect(lambda: open_file(str(p)))
        tab.page_changed.connect(lambda pno, prog: self._on_tab_progress(tab, pno, prog))
        tab.locator_changed.connect(lambda loc: self._on_tab_locator(tab, loc))

        tab_idx = self._tabs.addTab(tab, p.name)
        self._tabs.setCurrentIndex(tab_idx)

        # Restore locator or initial position
        if locator is not None:
            pno, y = backend.page_for(locator)
            tab.goto_page(pno, y)
        else:
            tab.goto_page(0)

        # Prefill highlight query if provided
        if highlight_query:
            tab.show_search()
            tab._search_input.setText(highlight_query)
            tab._on_search_next()

        self.show()
        self.raise_()
        self.activateWindow()
        return True

    def close_tab(self, index: int) -> None:
        """Close tab at index, flush position, and close window if last tab."""
        if 0 <= index < self._tabs.count():
            tab: ReaderTab = self._tabs.widget(index)
            # Emit final position
            loc = tab.backend.locator_for(tab.page_view.current_page, 0.0)
            if tab.book_id is not None:
                self.reading_position_saved.emit(tab.book_id, loc)

            tab.page_view._worker.stop()
            tab.backend.close()
            self._tabs.removeTab(index)

        if self._tabs.count() == 0:
            self.close()

    def closeEvent(self, event) -> None:
        while self._tabs.count() > 0:
            self.close_tab(0)
        super().closeEvent(event)

    def current_tab(self) -> ReaderTab | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, ReaderTab) else None

    # ── Slots & Actions ───────────────────────────────────────────────────────

    def _on_tab_progress(self, tab: ReaderTab, page: int, prog: float) -> None:
        if tab.book_id is not None:
            self.book_progress_updated.emit(tab.book_id, prog)

    def _on_tab_locator(self, tab: ReaderTab, loc: Locator) -> None:
        if tab.book_id is not None:
            self.reading_position_saved.emit(tab.book_id, loc)

    def _on_toggle_toc(self) -> None:
        t = self.current_tab()
        if t:
            t.toggle_toc()

    def _on_toggle_thumbnails(self) -> None:
        t = self.current_tab()
        if t:
            t.toggle_thumbnails()

    def _on_toggle_bookmark(self) -> None:
        t = self.current_tab()
        if t:
            t.toggle_bookmark_on_current_page()

    def _on_toggle_bookmarks_panel(self) -> None:
        t = self.current_tab()
        if t:
            t.toggle_bookmarks()

    def _on_toggle_notes_panel(self) -> None:
        t = self.current_tab()
        if t:
            t.toggle_notes()

    def _on_search(self) -> None:
        t = self.current_tab()
        if t:
            t.show_search()

    def _on_search_next_hit(self) -> None:
        t = self.current_tab()
        if t and t._search_bar.isVisible():
            t._on_search_next()

    def _on_search_prev_hit(self) -> None:
        t = self.current_tab()
        if t and t._search_bar.isVisible():
            t._on_search_prev()

    def _on_layout(self) -> None:
        t = self.current_tab()
        if t:
            t.open_settings_dialog()

    def _on_theme(self) -> None:
        t = self.current_tab()
        if t:
            t.cycle_theme()

    def _on_zoom_in(self) -> None:
        t = self.current_tab()
        if t:
            t.zoom_in()

    def _on_zoom_out(self) -> None:
        t = self.current_tab()
        if t:
            t.zoom_out()

    def _on_fit_width(self) -> None:
        t = self.current_tab()
        if t:
            t.fit_width()

    def _on_fit_page(self) -> None:
        t = self.current_tab()
        if t:
            t.fit_page()

    def _on_open_external(self) -> None:
        t = self.current_tab()
        if t:
            open_file(t.file_path)

    def _on_toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_esc(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            t = self.current_tab()
            if t and t._search_bar.isVisible():
                t.hide_search()

    def _on_next_page(self) -> None:
        t = self.current_tab()
        if t:
            t.next_page()

    def _on_prev_page(self) -> None:
        t = self.current_tab()
        if t:
            t.prev_page()

    def _on_first_page(self) -> None:
        t = self.current_tab()
        if t:
            t.goto_page(0)

    def _on_last_page(self) -> None:
        t = self.current_tab()
        if t:
            t.goto_page(t.backend.page_count - 1)

    def _on_close_current_tab(self) -> None:
        self.close_tab(self._tabs.currentIndex())

    def _on_next_tab(self) -> None:
        cnt = self._tabs.count()
        if cnt > 1:
            self._tabs.setCurrentIndex((self._tabs.currentIndex() + 1) % cnt)

    def _on_goto_page_dialog(self) -> None:
        t = self.current_tab()
        if not t:
            return
        total = max(1, t.backend.page_count)
        cur = t.page_view.current_page + 1
        page, ok = QInputDialog.getInt(self, "Go to Page", f"Enter page number (1-{total}):", cur, 1, total)
        if ok:
            t.goto_page(page - 1)
