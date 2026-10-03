"""
library_model.py – QAbstractTableModel for v2 (drives both grid and list views).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt
from PySide6.QtGui import QPixmap, QPixmapCache

from booklib.covers import cache as cover_cache
from booklib.db.repository import BookRow
from booklib.db.query import LibraryQuery

logger = logging.getLogger(__name__)

# ── Column definitions ────────────────────────────────────────────────────────

@dataclass
class Column:
    key: str
    header: str
    width: int = 100
    visible: bool = True


COLUMNS: list[Column] = [
    Column("cover",        "",            50,  True),
    Column("title",        "Title",       200, True),
    Column("author",       "Author",      150, True),
    Column("source",       "Source",      80,  True),
    Column("series",       "Series",      120, True),
    Column("year",         "Year",        60,  True),
    Column("format",       "Format",      60,  True),
    Column("size_bytes",   "Size",        80,  True),
    Column("pages",        "Pages",       60,  False),
    Column("progress",     "Progress",    80,  True),
    Column("status",       "Status",      90,  True),
    Column("rating",       "Rating",      80,  True),
    Column("publisher",    "Publisher",   120, False),
    Column("genre",        "Genre",       100, False),
    Column("tags",         "Tags",        100, False),
    Column("language",     "Language",    80,  False),
    Column("isbn",         "ISBN",        120, False),
    Column("date_added",   "Added",       100, False),
    Column("last_opened",  "Last Opened", 100, False),
]

COL_IDX = {c.key: i for i, c in enumerate(COLUMNS)}

# Custom Qt roles
ROLE_BOOK_ID      = Qt.UserRole + 1
ROLE_AUTHOR       = Qt.UserRole + 2
ROLE_STATUS       = Qt.UserRole + 3
ROLE_RATING       = Qt.UserRole + 4
ROLE_FORMAT       = Qt.UserRole + 5
ROLE_PATH         = Qt.UserRole + 6
ROLE_MISSING      = Qt.UserRole + 7
ROLE_BOOK_ROW     = Qt.UserRole + 8   # full BookRow object
ROLE_PROGRESS     = Qt.UserRole + 9   # (progress_page, progress_percent, pages)
ROLE_SOURCE_BADGE = Qt.UserRole + 10  # CLOUD, CACHED, PINNED, or None

THUMBNAIL_SIZE = QSize(120, 170)



class LibraryModel(QAbstractTableModel):
    """Holds BookRow records for both grid and list views."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._books: list[BookRow] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def reset_books(self, books: list[BookRow]) -> None:
        self.beginResetModel()
        self._books = books
        self.endResetModel()

    def book_at(self, index: QModelIndex) -> BookRow | None:
        if index.isValid() and 0 <= index.row() < len(self._books):
            return self._books[index.row()]
        return None

    def book_by_id(self, book_id: int) -> BookRow | None:
        for b in self._books:
            if b.id == book_id:
                return b
        return None

    def index_for_id(self, book_id: int) -> QModelIndex:
        for i, b in enumerate(self._books):
            if b.id == book_id:
                return self.index(i, 0)
        return QModelIndex()

    def update_row(self, book_id: int, book: BookRow) -> None:
        """Update a single row without a full model reset."""
        for i, b in enumerate(self._books):
            if b.id == book_id:
                self._books[i] = book
                top = self.index(i, 0)
                bot = self.index(i, len(COLUMNS) - 1)
                self.dataChanged.emit(top, bot)
                return

    def remove_row_by_id(self, book_id: int) -> None:
        for i, b in enumerate(self._books):
            if b.id == book_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._books.pop(i)
                self.endRemoveRows()
                return

    def selected_book_ids(self, selection_model) -> list[int]:
        seen: set[int] = set()
        ids: list[int] = []
        for idx in selection_model.selectedRows():
            book = self.book_at(idx)
            if book and book.id not in seen:
                ids.append(book.id)
                seen.add(book.id)
        return ids

    # ── QAbstractTableModel overrides ─────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._books)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section].header
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._books)):
            return None
        book = self._books[index.row()]
        col = COLUMNS[index.column()].key

        # ── Custom roles (row 0 / column 0 only) ─────────────────────────────
        if role == ROLE_BOOK_ID:
            return book.id
        if role == ROLE_AUTHOR:
            return book.author
        if role == ROLE_STATUS:
            return book.status
        if role == ROLE_RATING:
            return book.rating
        if role == ROLE_FORMAT:
            return book.format
        if role == ROLE_PATH:
            return book.path
        if role == ROLE_MISSING:
            return book.is_missing
        if role == ROLE_BOOK_ROW:
            return book
        if role == ROLE_PROGRESS:
            return (book.progress_page, book.progress_percent, book.pages)
        if role == ROLE_SOURCE_BADGE:
            if book.source == "gdrive":
                if book.keep_offline:
                    return "PINNED"
                elif book.is_cached:
                    return "CACHED"
                else:
                    return "CLOUD"
            return None

        # ── Standard roles ────────────────────────────────────────────────────
        if role == Qt.DisplayRole:
            return self._display(book, col)
        if role == Qt.DecorationRole and col == "cover":
            return self._load_pixmap(book)
        if role == Qt.ToolTipRole:
            return book.path
        if role == Qt.UserRole:
            return book.id

        return None

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _display(book: BookRow, col: str) -> str | None:
        from booklib.utils.format import human_size, dash_if_none

        # Source string
        source_str = "Local"
        if book.source == "gdrive":
            if book.keep_offline:
                source_str = "Offline"
            elif book.is_cached:
                source_str = "Cached"
            else:
                source_str = "Drive"

        # Series string
        series_str = None
        if book.series_name:
            if book.series_index is not None:
                series_str = f"{book.series_name} #{book.series_index}"
            else:
                series_str = book.series_name

        # Progress string
        progress_str = "—"
        if book.progress_page and book.pages:
            pct = int((book.progress_page / book.pages) * 100)
            progress_str = f"{book.progress_page} / {book.pages} ({pct}%)"
        elif book.progress_percent is not None and book.progress_percent > 0:
            progress_str = f"{int(book.progress_percent)}%"

        mapping = {
            "cover":       None,
            "title":       book.title or "Unknown",
            "author":      dash_if_none(book.author),
            "source":      source_str,
            "series":      dash_if_none(series_str),
            "year":        dash_if_none(book.year),
            "format":      book.format.upper(),
            "size_bytes":  human_size(book.size_bytes),
            "pages":       dash_if_none(book.pages),
            "progress":    progress_str,
            "status":      {None: "—", "want": "Want", "reading": "Reading", "read": "Read"}.get(book.status, "—"),
            "rating":      ("★" * (book.rating or 0)) or "—",
            "publisher":   dash_if_none(book.publisher),
            "genre":       dash_if_none(book.genre),
            "tags":        dash_if_none(book.tags_text),
            "language":    dash_if_none(book.language),
            "isbn":        dash_if_none(book.isbn),
            "date_added":  (book.date_added or "")[:10] or "—",
            "last_opened": (book.last_opened_at or "")[:10] or "—",
        }
        return mapping.get(col)


    def _load_pixmap(self, book: BookRow) -> QPixmap:
        key = book.cover_path or f"_placeholder_{book.format}"
        cached = QPixmapCache.find(key)
        if cached and not cached.isNull():
            return cached

        px = QPixmap()
        if book.cover_path and cover_cache.exists(book.cover_path):
            px.load(str(cover_cache.absolute_path(book.cover_path)))

        if px.isNull():
            try:
                from booklib.covers.placeholder import generate_placeholder
                px.loadFromData(generate_placeholder(book.format))
            except Exception:
                pass

        if not px.isNull():
            px = px.scaled(THUMBNAIL_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            QPixmapCache.insert(key, px)

        return px
