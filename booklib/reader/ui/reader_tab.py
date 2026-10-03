"""
reader/ui/reader_tab.py – Single document reader tab with canvas and local controls.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from booklib.reader.annotations import add_annotation, list_annotations
from booklib.reader.backend import DocumentBackend, Hit, Link, Locator
from booklib.reader.bookmarks import (
    add_bookmark,
    delete_bookmark,
    get_bookmarked_pages,
    list_bookmarks,
)
from booklib.reader.layout import LayoutSettings
from booklib.reader.search import SearchState
from booklib.reader.ui.bookmarks_panel import BookmarksPanel
from booklib.reader.ui.notes_panel import NotesPanel
from booklib.reader.ui.page_view import PageView
from booklib.reader.ui.selection_popup import SelectionPopup
from booklib.reader.ui.settings_popover import SettingsDialog
from booklib.reader.ui.thumbs_panel import ThumbsPanel
from booklib.reader.ui.toc_panel import TocPanel

logger = logging.getLogger(__name__)


class ReaderTab(QWidget):
    """Encapsulates a single open document, canvas, search bar, and side panels."""

    page_changed = Signal(int, float)       # page (0-based), progress fraction (0..1)
    locator_changed = Signal(object)        # Locator
    open_external_requested = Signal()

    def __init__(
        self,
        backend: DocumentBackend,
        file_path: str,
        book_id: int | None = None,
        conn_supplier=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.file_path = file_path
        self.book_id = book_id
        self._conn_supplier = conn_supplier
        self.search_state = SearchState()
        self.settings = LayoutSettings.load_global()

        # Selection state
        self._last_selected_text = ""
        self._last_selected_page = -1
        self._last_selected_rects = []

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Search Bar (collapsible) ──────────────────────────────────────────
        self._search_bar = QWidget(self)
        s_layout = QHBoxLayout(self._search_bar)
        s_layout.setContentsMargins(8, 4, 8, 4)
        s_layout.addWidget(QLabel("Find in book:", self))

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("Search words or phrases…")
        self._search_input.returnPressed.connect(self._on_search_next)
        s_layout.addWidget(self._search_input)

        self._search_info = QLabel("", self)
        s_layout.addWidget(self._search_info)

        self._btn_prev_hit = QToolButton(self)
        self._btn_prev_hit.setIcon(self.style().standardIcon(QStyle.SP_ArrowBack))
        self._btn_prev_hit.setToolTip("Previous hit (Shift+F3)")
        self._btn_prev_hit.clicked.connect(self._on_search_prev)
        s_layout.addWidget(self._btn_prev_hit)

        self._btn_next_hit = QToolButton(self)
        self._btn_next_hit.setIcon(self.style().standardIcon(QStyle.SP_ArrowForward))
        self._btn_next_hit.setToolTip("Next hit (F3)")
        self._btn_next_hit.clicked.connect(self._on_search_next)
        s_layout.addWidget(self._btn_next_hit)

        btn_close_search = QToolButton(self)
        btn_close_search.setText("×")
        btn_close_search.clicked.connect(self.hide_search)
        s_layout.addWidget(btn_close_search)

        self._search_bar.hide()
        main_layout.addWidget(self._search_bar)

        # ── Main Content Splitter (Side Panels + Canvas) ──────────────────────
        self._splitter = QSplitter(Qt.Horizontal, self)

        # Side panel stack (TOC, Thumbnails, Bookmarks, Notes)
        self._side_stack = QStackedWidget(self)

        self._toc_panel = TocPanel(self)
        self._toc_panel.item_selected.connect(self.goto_page)
        self._side_stack.addWidget(self._toc_panel)

        self._thumbs_panel = ThumbsPanel(backend, self)
        self._thumbs_panel.item_selected.connect(self.goto_page)
        self._side_stack.addWidget(self._thumbs_panel)

        self._bookmarks_panel = BookmarksPanel(self._get_conn, book_id=book_id, parent=self)
        self._bookmarks_panel.bookmark_jump.connect(self._on_bookmark_jump)
        self._bookmarks_panel.bookmarks_changed.connect(self._refresh_bookmarks_overlay)
        self._side_stack.addWidget(self._bookmarks_panel)

        self._notes_panel = NotesPanel(self._get_conn, book_id=book_id, file_path=file_path, parent=self)
        self._notes_panel.annotation_jump.connect(self._on_annotation_jump)
        self._notes_panel.annotations_changed.connect(self._refresh_annotations_overlay)
        self._side_stack.addWidget(self._notes_panel)

        self._side_stack.hide()
        self._splitter.addWidget(self._side_stack)

        # Page View Canvas
        self.page_view = PageView(backend, self.settings, self)
        self.page_view.page_changed.connect(self._on_page_changed)
        self.page_view.text_selected.connect(self._on_text_selected)
        self.page_view.open_external_requested.connect(self.open_external_requested)
        self._splitter.addWidget(self.page_view)

        # Selection popup
        self._sel_popup = SelectionPopup(self)
        self._sel_popup.highlight_requested.connect(self._on_highlight_requested)
        self._sel_popup.note_requested.connect(self._on_note_requested)
        self._sel_popup.copy_requested.connect(self._on_copy_requested)

        # Splitter sizing: side panel 260px, canvas rest
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self._splitter, 1)

        # ── Bottom Navigation Bar ─────────────────────────────────────────────
        bottom_bar = QWidget(self)
        b_layout = QHBoxLayout(bottom_bar)
        b_layout.setContentsMargins(12, 4, 12, 4)

        self._btn_prev_page = QPushButton("◀", self)
        self._btn_prev_page.setFixedWidth(32)
        self._btn_prev_page.setToolTip("Previous Page (Left / PageUp)")
        self._btn_prev_page.clicked.connect(self.prev_page)
        b_layout.addWidget(self._btn_prev_page)

        self._page_label = QLabel("Page 1 of 1", self)
        b_layout.addWidget(self._page_label)

        self._page_slider = QSlider(Qt.Horizontal, self)
        self._page_slider.setRange(1, max(1, self.backend.page_count))
        self._page_slider.valueChanged.connect(lambda v: self.goto_page(v - 1))
        b_layout.addWidget(self._page_slider, 1)

        self._btn_next_page = QPushButton("▶", self)
        self._btn_next_page.setFixedWidth(32)
        self._btn_next_page.setToolTip("Next Page (Right / PageDown)")
        self._btn_next_page.clicked.connect(self.next_page)
        b_layout.addWidget(self._btn_next_page)

        self._progress_label = QLabel("0%", self)
        b_layout.addWidget(self._progress_label)

        self._time_left_label = QLabel("", self)
        self._time_left_label.setStyleSheet("color: gray;")
        b_layout.addWidget(self._time_left_label)

        main_layout.addWidget(bottom_bar)

        # Load TOC entries
        self._toc_panel.load_toc(self.backend.toc())
        self._update_navigation_labels(0)

    def closeEvent(self, event) -> None:
        self.page_view._worker.stop()
        super().closeEvent(event)

    # ── Navigation & Paging ───────────────────────────────────────────────────

    def goto_page(self, page: int, y_frac: float = 0.0) -> None:
        self.page_view.goto_page(page, y_frac)

    def next_page(self) -> None:
        if self.page_view.current_page < self.backend.page_count - 1:
            self.goto_page(self.page_view.current_page + 1)

    def prev_page(self) -> None:
        if self.page_view.current_page > 0:
            self.goto_page(self.page_view.current_page - 1)

    def _on_page_changed(self, page: int) -> None:
        self._update_navigation_labels(page)
        progress = float(page + 1) / max(self.backend.page_count, 1)
        self.page_changed.emit(page, progress)
        loc = self.backend.locator_for(page, 0.0)
        self.locator_changed.emit(loc)

    def _update_navigation_labels(self, page: int) -> None:
        total = max(self.backend.page_count, 1)
        cur = page + 1
        self._page_label.setText(f"Page {cur} of {total}")
        self._page_slider.blockSignals(True)
        self._page_slider.setValue(cur)
        self._page_slider.blockSignals(False)
        pct = int((cur / total) * 100)
        self._progress_label.setText(f"{pct}%")

    def set_time_left(self, text: str) -> None:
        self._time_left_label.setText(text)

    # ── Panels ────────────────────────────────────────────────────────────────

    def toggle_toc(self) -> None:
        if self._side_stack.isVisible() and self._side_stack.currentWidget() == self._toc_panel:
            self._side_stack.hide()
        else:
            self._side_stack.setCurrentWidget(self._toc_panel)
            self._side_stack.show()

    def toggle_thumbnails(self) -> None:
        if self._side_stack.isVisible() and self._side_stack.currentWidget() == self._thumbs_panel:
            self._side_stack.hide()
        else:
            self._side_stack.setCurrentWidget(self._thumbs_panel)
            self._side_stack.show()

    # ── Search ────────────────────────────────────────────────────────────────

    def show_search(self) -> None:
        self._search_bar.show()
        self._search_input.setFocus()
        self._search_input.selectAll()

    def hide_search(self) -> None:
        self._search_bar.hide()
        self.search_state.clear()
        self.page_view.set_search_hits([])
        self.page_view.setFocus()

    def _on_search_next(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            return

        if query != self.search_state.query:
            hits = self.backend.search(query)
            self.search_state.set_results(query, hits)
            self.page_view.set_search_hits(hits)

        hit = self.search_state.next_hit()
        self._navigate_to_hit(hit)

    def _on_search_prev(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            return

        if query != self.search_state.query:
            hits = self.backend.search(query)
            self.search_state.set_results(query, hits)
            self.page_view.set_search_hits(hits)

        hit = self.search_state.prev_hit()
        self._navigate_to_hit(hit)

    def _navigate_to_hit(self, hit: Hit | None) -> None:
        if hit is None:
            self._search_info.setText("0 matches")
            self.page_view.set_search_hits([])
            return

        self._search_info.setText(f"{self.search_state.display_index} of {self.search_state.total_count}")
        self.page_view.set_search_hits(self.search_state.hits, active_hit=hit)
        self.goto_page(hit.page)

    # ── Layout & Typography ───────────────────────────────────────────────────

    def open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self.settings, is_reflowable=self.backend.is_reflowable, parent=self)
        dlg.settings_changed.connect(self.page_view.update_settings)
        dlg.exec()

    def cycle_theme(self) -> None:
        order = ["light", "sepia", "dark", "black"]
        idx = order.index(self.settings.theme) if self.settings.theme in order else 0
        next_theme = order[(idx + 1) % len(order)]
        self.settings.theme = next_theme
        self.settings.save_global()
        self.page_view.update_settings(self.settings)

    def zoom_in(self) -> None:
        self.settings.fit_mode = "custom"
        self.settings.zoom = min(self.settings.zoom + 0.15, 4.0)
        self.page_view.update_settings(self.settings)

    def zoom_out(self) -> None:
        self.settings.fit_mode = "custom"
        self.settings.zoom = max(self.settings.zoom - 0.15, 0.25)
        self.page_view.update_settings(self.settings)

    def fit_width(self) -> None:
        self.settings.fit_mode = "width"
        self.page_view.update_settings(self.settings)

    def fit_page(self) -> None:
        self.settings.fit_mode = "page"
        self.page_view.update_settings(self.settings)

    # ── Bookmarks & Annotations ───────────────────────────────────────────────

    def _get_conn(self):
        if self._conn_supplier:
            return self._conn_supplier()
        return None

    def toggle_bookmarks(self) -> None:
        if self._side_stack.isVisible() and self._side_stack.currentWidget() == self._bookmarks_panel:
            self._side_stack.hide()
        else:
            self._bookmarks_panel.reload()
            self._side_stack.setCurrentWidget(self._bookmarks_panel)
            self._side_stack.show()

    def toggle_notes(self) -> None:
        if self._side_stack.isVisible() and self._side_stack.currentWidget() == self._notes_panel:
            self._side_stack.hide()
        else:
            self._notes_panel.reload()
            self._side_stack.setCurrentWidget(self._notes_panel)
            self._side_stack.show()

    def toggle_bookmark_on_current_page(self) -> None:
        conn = self._get_conn()
        if not conn or not self.book_id:
            return
        pno = self.page_view.current_page
        bms = list_bookmarks(conn, self.book_id)
        matching = [b for b in bms if (b.get("locator_obj") or Locator.from_json(b.get("locator", "{}"))).page == pno]
        if matching:
            for b in matching:
                delete_bookmark(conn, b["id"])
        else:
            words = self.page_view.text_layer.get_words(pno)
            snippet = " ".join(w.text for w in words[:10]) if words else ""
            loc = self.backend.locator_for(pno, 0.0)
            add_bookmark(conn, self.book_id, loc, label=f"Page {pno + 1}", snippet=snippet)

        self._refresh_bookmarks_overlay()
        self._bookmarks_panel.reload()

    def _refresh_bookmarks_overlay(self) -> None:
        conn = self._get_conn()
        if conn and self.book_id:
            pages = get_bookmarked_pages(conn, self.book_id)
            self.page_view.set_bookmarks(pages)

    def _refresh_annotations_overlay(self) -> None:
        conn = self._get_conn()
        if conn and self.book_id:
            annots = list_annotations(conn, book_id=self.book_id)
            rects_by_page: dict[int, list[tuple[tuple[float, float, float, float], str]]] = {}
            for a in annots:
                loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
                if loc.page is not None:
                    hits = self.backend.search(a["quote"][:30])
                    for h in hits:
                        if h.page == loc.page:
                            for r in h.rects:
                                rects_by_page.setdefault(loc.page, []).append((r, a["color"]))
            self.page_view.set_annotations(rects_by_page)

    def _on_bookmark_jump(self, loc: Locator) -> None:
        p, y = self.backend.page_for(loc)
        self.goto_page(p, y)

    def _on_annotation_jump(self, loc: Locator) -> None:
        p, y = self.backend.page_for(loc)
        self.goto_page(p, y)

    def _on_text_selected(self, page: int, text: str, rects: list) -> None:
        self._last_selected_page = page
        self._last_selected_text = text
        self._last_selected_rects = rects
        from PySide6.QtGui import QCursor
        cursor_pos = QCursor.pos()
        self._sel_popup.move(cursor_pos.x() + 10, cursor_pos.y() - 30)
        self._sel_popup.show()

    def _on_highlight_requested(self, color: str) -> None:
        conn = self._get_conn()
        if not conn or not self.book_id or not self._last_selected_text:
            return
        pno = self._last_selected_page
        loc = self.backend.locator_for(pno, 0.0)
        add_annotation(
            conn,
            book_id=self.book_id,
            kind="highlight",
            color=color,
            quote=self._last_selected_text,
            locator=loc,
        )
        self._refresh_annotations_overlay()
        self._notes_panel.reload()

    def _on_note_requested(self) -> None:
        conn = self._get_conn()
        if not conn or not self.book_id or not self._last_selected_text:
            return
        note, ok = QInputDialog.getMultiLineText(self, "Add Note", f"Note for \"{self._last_selected_text[:40]}…\":")
        if ok and note.strip():
            pno = self._last_selected_page
            loc = self.backend.locator_for(pno, 0.0)
            add_annotation(
                conn,
                book_id=self.book_id,
                kind="note",
                color="yellow",
                quote=self._last_selected_text,
                locator=loc,
                note=note.strip(),
            )
            self._refresh_annotations_overlay()
            self._notes_panel.reload()

    def _on_copy_requested(self) -> None:
        if self._last_selected_text:
            from PySide6.QtGui import QGuiApplication
            clip = QGuiApplication.clipboard()
            if clip:
                clip.setText(self._last_selected_text)
