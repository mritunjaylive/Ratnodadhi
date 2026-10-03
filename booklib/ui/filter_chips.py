"""
filter_chips.py – Active filter chips bar with removable tags and 'Clear all'.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget,
)

from booklib.db.query import LibraryQuery


class FilterChips(QWidget):
    """
    Displays horizontal chips for active filters, search, and shelf selections.
    Emits signals when an individual filter is removed or all are cleared.
    """

    filter_cleared = Signal(str, object)  # (filter_kind, value)
    clear_all_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setVisible(False)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 2, 8, 2)
        outer.setSpacing(6)

        self._lbl = QLabel("Filters:")
        self._lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: palette(window-text);")
        outer.addWidget(self._lbl)

        self._chips_container = QWidget()
        self._chips_layout = QHBoxLayout(self._chips_container)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(self._chips_container)
        scroll.setFixedHeight(30)
        outer.addWidget(scroll, 1)

        self._save_smart_btn = QPushButton("Save as smart collection…")
        self._save_smart_btn.setFlat(True)
        self._save_smart_btn.setStyleSheet(
            "QPushButton { font-size: 11px; color: palette(highlight); font-weight: bold; padding: 2px 6px; }"
            "QPushButton:hover { text-decoration: underline; }"
        )
        self._save_smart_btn.clicked.connect(self.save_smart_collection_requested.emit)
        outer.addWidget(self._save_smart_btn)

        self._clear_all_btn = QPushButton("Clear all")
        self._clear_all_btn.setFlat(True)
        self._clear_all_btn.setStyleSheet(
            "QPushButton { font-size: 11px; color: #ef4444; font-weight: bold; padding: 2px 6px; }"
            "QPushButton:hover { text-decoration: underline; }"
        )
        self._clear_all_btn.clicked.connect(self.clear_all_requested.emit)
        outer.addWidget(self._clear_all_btn)

    save_smart_collection_requested = Signal()

    def set_query(self, query: LibraryQuery) -> None:
        """Rebuild chips from the given LibraryQuery."""
        # Clear existing chips
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        chip_count = 0

        # Search chip
        if query.search:
            self._add_chip(f'Search: "{query.search}"', "search", query.search)
            chip_count += 1

        # Shelf chip
        if query.shelf:
            shelf_labels = {
                "continue": "Continue Reading",
                "recent": "Recently Added",
                "recommended": "Recommended",
            }
            shelf_name = shelf_labels.get(query.shelf, query.shelf.replace("_", " ").title())
            self._add_chip(f"Shelf: {shelf_name}", "shelf", query.shelf)
            chip_count += 1

        # Status chips
        status_labels = {"want": "Want to Read", "reading": "Reading", "read": "Read", "none": "Unset"}
        for s in sorted(query.statuses):
            self._add_chip(f"Status: {status_labels.get(s, s)}", "status", s)
            chip_count += 1

        # Format chips
        for fmt in sorted(query.formats):
            self._add_chip(f"Format: {fmt.upper()}", "format", fmt)
            chip_count += 1

        # Author chips
        for author in sorted(query.authors):
            self._add_chip(f"Author: {author}", "author", author)
            chip_count += 1

        # Genre chips
        for genre in sorted(query.genres):
            self._add_chip(f"Genre: {genre}", "genre", genre)
            chip_count += 1

        # Language chips
        for lang in sorted(query.languages):
            self._add_chip(f"Lang: {lang}", "language", lang)
            chip_count += 1

        # Rating chip
        if query.min_rating is not None:
            self._add_chip(f"Rating: ≥ {query.min_rating} stars", "min_rating", query.min_rating)
            chip_count += 1

        # Tag chips
        if query.tag_ids:
            self._add_chip(f"Tags ({len(query.tag_ids)}, {query.tag_mode})", "tag_ids", None)
            chip_count += 1

        # Series chip
        if query.series_id is not None:
            self._add_chip(f"Series Filter", "series_id", query.series_id)
            chip_count += 1

        # Lookup status chip
        if query.lookup_status:
            self._add_chip(f"Needs Review", "lookup_status", query.lookup_status)
            chip_count += 1

        # Incomplete chip
        if query.incomplete:
            self._add_chip("Incomplete Metadata", "incomplete", True)
            chip_count += 1

        # In-book search matches chip
        if query.book_ids:
            self._add_chip(f"Matching In-Book Search ({len(query.book_ids)})", "book_ids", None)
            chip_count += 1

        self._chips_layout.addStretch()
        self.setVisible(chip_count > 0)

    def _add_chip(self, label: str, kind: str, value: object) -> None:
        btn = QPushButton(f"{label}  ×")
        btn.setStyleSheet(
            "QPushButton {"
            "  background: palette(alternate-base);"
            "  color: palette(window-text);"
            "  border: 1px solid palette(mid);"
            "  border-radius: 10px;"
            "  padding: 2px 8px;"
            "  font-size: 11px;"
            "}"
            "QPushButton:hover {"
            "  background: palette(button);"
            "  border-color: palette(highlight);"
            "}"
        )
        btn.clicked.connect(lambda: self.filter_cleared.emit(kind, value))
        self._chips_layout.addWidget(btn)

