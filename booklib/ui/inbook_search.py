"""
ui/inbook_search.py – Global in-book search dialog (Ctrl+Shift+F).
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QTextDocument

from booklib.fulltext.query import SearchHit, SearchResultGroup, search_inside_books
from booklib.fulltext.store import get_fulltext_store
from booklib.reader.backend import Locator
from booklib.reader.manager import get_reader_manager

logger = logging.getLogger(__name__)


class HtmlSnippetDelegate(QStyledItemDelegate):
    """Renders HTML markup in search snippets within QTreeWidget."""

    def paint(self, painter, option, index):
        options = QStyleOptionViewItem(option)
        self.initStyleOption(options, index)

        painter.save()
        doc = QTextDocument()
        doc.setHtml(options.text)

        # Draw selection background if selected
        if options.state & option.State_Selected:
            painter.fillRect(options.rect, options.palette.highlight())

        painter.translate(options.rect.left(), options.rect.top())
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):
        options = QStyleOptionViewItem(option)
        self.initStyleOption(options, index)
        doc = QTextDocument()
        doc.setHtml(options.text)
        return doc.size().toSize()


class InBookSearchDialog(QDialog):
    """
    Search inside books dialog supporting full-text query syntax,
    grouped tree results, on-demand snippets, and jump to reader.
    """

    show_books_in_library_requested = Signal(list)  # list of book_ids

    def __init__(self, db_conn_supplier, parent=None, current_book_ids: list[int] | None = None) -> None:
        super().__init__(parent)
        self.db_conn_supplier = db_conn_supplier
        self.current_book_ids = current_book_ids
        self.store = get_fulltext_store()

        self.setWindowTitle("Search Inside Books")
        self.resize(850, 600)
        self.setMinimumSize(600, 400)

        self._results: list[SearchResultGroup] = []
        self._book_titles: dict[int, tuple[str, str]] = {}  # id -> (title, author)

        self._setup_ui()
        self._load_book_metadata()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── Top Search Input Bar ──────────────────────────────────────────────
        top_bar = QHBoxLayout()

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText('Search words or phrases inside books… e.g. "clean architecture", -legacy')
        self._search_input.returnPressed.connect(self._on_search)
        top_bar.addWidget(self._search_input, 1)

        self._scope_combo = QComboBox(self)
        self._scope_combo.addItem("All Indexed Books", "all")
        if self.current_book_ids:
            self._scope_combo.addItem(f"Current Library View ({len(self.current_book_ids)} books)", "filtered")
        self._scope_combo.currentIndexChanged.connect(self._on_search)
        top_bar.addWidget(self._scope_combo)

        btn_search = QPushButton("Search", self)
        btn_search.setDefault(True)
        btn_search.clicked.connect(self._on_search)
        top_bar.addWidget(btn_search)

        layout.addLayout(top_bar)

        # ── Status Label ──────────────────────────────────────────────────────
        self._status_label = QLabel("Enter keywords to search across book contents.", self)
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._status_label)

        # ── Tree Results View ─────────────────────────────────────────────────
        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Location", "Matched Snippet"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self._tree.setItemDelegateForColumn(1, HtmlSnippetDelegate(self._tree))
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree, 1)

        # ── Bottom Action Bar ─────────────────────────────────────────────────
        bottom_bar = QHBoxLayout()

        self._btn_filter_library = QPushButton("Show These Books in Library", self)
        self._btn_filter_library.setEnabled(False)
        self._btn_filter_library.clicked.connect(self._on_show_in_library)
        bottom_bar.addWidget(self._btn_filter_library)

        bottom_bar.addStretch()

        self._btn_open_reader = QPushButton("Open in Reader", self)
        self._btn_open_reader.setEnabled(False)
        self._btn_open_reader.clicked.connect(self._on_open_selected_hit)
        bottom_bar.addWidget(self._btn_open_reader)

        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.close)
        bottom_bar.addWidget(btn_close)

        layout.addLayout(bottom_bar)

        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)

    def _load_book_metadata(self) -> None:
        conn = self.db_conn_supplier()
        if not conn:
            return
        rows = conn.execute("SELECT id, title, author FROM books").fetchall()
        for r in rows:
            self._book_titles[r["id"]] = (r["title"] or "Untitled", r["author"] or "Unknown Author")

    def _on_search(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            self._tree.clear()
            self._status_label.setText("Please enter a search query.")
            self._btn_filter_library.setEnabled(False)
            return

        scope = self._scope_combo.currentData()
        book_ids = self.current_book_ids if scope == "filtered" else None

        self._status_label.setText("Searching…")
        self._tree.clear()

        self._results = search_inside_books(self.store, query, book_ids=book_ids)

        if not self._results:
            self._status_label.setText(f'No matches found for "{query}".')
            self._btn_filter_library.setEnabled(False)
            return

        total_matches = sum(g.total_hits for g in self._results)
        book_count = len(self._results)
        self._status_label.setText(f'Found {total_matches} match{"es" if total_matches != 1 else ""} across {book_count} book{"s" if book_count != 1 else ""}.')
        self._btn_filter_library.setEnabled(True)

        # Populate tree
        bold_font = QFont()
        bold_font.setBold(True)

        for group in self._results:
            bid = group.book_id
            title, author = self._book_titles.get(bid, (f"Book #{bid}", ""))

            book_item = QTreeWidgetItem(self._tree)
            book_item.setText(0, title)
            book_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
            book_item.setFont(0, bold_font)
            book_item.setText(1, f"{author} — {group.total_hits} match{'es' if group.total_hits != 1 else ''}")
            book_item.setData(0, Qt.UserRole, ("book", bid, None))
            book_item.setExpanded(True)

            for hit in group.hits:
                hit_item = QTreeWidgetItem(book_item)
                hit_item.setText(0, f"Page {hit.page_number + 1}")
                hit_item.setText(1, hit.snippet)
                hit_item.setData(0, Qt.UserRole, ("hit", bid, hit))

    def _on_tree_selection_changed(self) -> None:
        sel = self._tree.selectedItems()
        self._btn_open_reader.setEnabled(bool(sel))

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        self._open_item(item)

    def _on_open_selected_hit(self) -> None:
        sel = self._tree.selectedItems()
        if sel:
            self._open_item(sel[0])

    def _open_item(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, book_id, hit = data
        page = hit.page_number if hit else 0
        loc = Locator(page=page)

        query = self._search_input.text().strip()
        mgr = get_reader_manager(self.db_conn_supplier)
        mgr.open_book(book_id, locator=loc, highlight_query=query)

    def _on_show_in_library(self) -> None:
        book_ids = [g.book_id for g in self._results]
        self.show_books_in_library_requested.emit(book_ids)
        self.accept()
