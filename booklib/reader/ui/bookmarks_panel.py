"""
reader/ui/bookmarks_panel.py – Bookmarks list, jump, rename, and delete panel.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from booklib.reader.backend import Locator
from booklib.reader.bookmarks import delete_bookmark, list_bookmarks, rename_bookmark


class BookmarksPanel(QWidget):
    """Panel displaying bookmarks with jump, edit, and delete controls."""

    bookmark_jump = Signal(object)  # Locator
    bookmarks_changed = Signal()

    def __init__(self, conn_supplier, book_id: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self._conn_supplier = conn_supplier
        self._book_id = book_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._list = QListWidget(self)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)

        self._empty_label = QLabel("No bookmarks yet.\nPress Ctrl+D on any page to bookmark.", self)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: gray; padding: 20px;")
        layout.addWidget(self._empty_label)

        btn_layout = QHBoxLayout()
        self._btn_jump = QPushButton("Jump", self)
        self._btn_jump.clicked.connect(self._on_jump)
        btn_layout.addWidget(self._btn_jump)

        self._btn_rename = QPushButton("Rename", self)
        self._btn_rename.clicked.connect(self._on_rename)
        btn_layout.addWidget(self._btn_rename)

        self._btn_delete = QPushButton("Delete", self)
        self._btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self._btn_delete)

        layout.addLayout(btn_layout)
        self.reload()

    def set_book_id(self, book_id: int | None) -> None:
        self._book_id = book_id
        self.reload()

    def reload(self) -> None:
        """Reload bookmarks from database."""
        self._list.clear()
        if self._book_id is None:
            self._list.hide()
            self._empty_label.show()
            return

        conn = self._conn_supplier()
        if not conn:
            return

        bms = list_bookmarks(conn, self._book_id)
        if not bms:
            self._list.hide()
            self._empty_label.show()
            return

        self._empty_label.hide()
        self._list.show()

        for b in bms:
            item = QListWidgetItem(f"{b['label']}\n   \"{b['snippet']}\"")
            item.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
            item.setData(Qt.UserRole, b)
            self._list.addItem(item)

    def _selected_item(self) -> dict[str, Any] | None:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_jump(self) -> None:
        b = self._selected_item()
        if b:
            self.bookmark_jump.emit(b["locator_obj"])

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._on_jump()

    def _on_rename(self) -> None:
        b = self._selected_item()
        if not b:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Bookmark", "New bookmark label:", text=b["label"])
        if ok and new_name.strip():
            conn = self._conn_supplier()
            if conn:
                rename_bookmark(conn, b["id"], new_name.strip())
                self.reload()
                self.bookmarks_changed.emit()

    def _on_delete(self) -> None:
        b = self._selected_item()
        if not b:
            return
        if QMessageBox.question(self, "Delete Bookmark", "Delete this bookmark?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            conn = self._conn_supplier()
            if conn:
                delete_bookmark(conn, b["id"])
                self.reload()
                self.bookmarks_changed.emit()
