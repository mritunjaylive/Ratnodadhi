"""
duplicates_dialog.py – Duplicate books review and resolution dialog.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QRadioButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from booklib.config import COVERS_DIR
from booklib.db.database import Database
from booklib.duplicates.actions import ignore_group, remove_from_library, send_to_recycle_bin
from booklib.duplicates.finder import DuplicateGroup, find_duplicate_groups
from booklib.duplicates.merge import merge_book_user_data

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


class DuplicatesDialog(QDialog):
    """Dialog to review duplicate book groups and safely resolve them."""
    resolved = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.groups: list[DuplicateGroup] = []
        self.current_group_idx = 0
        self.keeper_id: int | None = None

        self.setWindowTitle("Find and Resolve Duplicates")
        self.resize(950, 650)
        self._setup_ui()
        self._load_groups()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)

        # Left: Groups List
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(0, 0, 0, 0)
        self.group_count_lbl = QLabel("Duplicate Groups:")
        self.group_count_lbl.setStyleSheet("font-weight: bold;")
        left_l.addWidget(self.group_count_lbl)

        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self._on_group_selected)
        left_l.addWidget(self.group_list)
        splitter.addWidget(left_w)

        # Right: Comparison & Actions
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)

        self.group_title_lbl = QLabel()
        self.group_title_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        right_l.addWidget(self.group_title_lbl)

        # Comparison table: Rows = Attributes, Cols = Books
        self.comp_table = QTableWidget()
        right_l.addWidget(self.comp_table)

        # Controls row
        ctrl_row = QHBoxLayout()
        self.merge_cb = QCheckBox("Merge reading data, tags & notes into keeper")
        self.merge_cb.setChecked(True)
        ctrl_row.addWidget(self.merge_cb)
        ctrl_row.addStretch()
        right_l.addLayout(ctrl_row)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_ignore = QPushButton("Keep both (Not a duplicate)")
        self.btn_ignore.clicked.connect(self._on_ignore)
        btn_row.addWidget(self.btn_ignore)

        self.btn_remove_db = QPushButton("Remove duplicates from library only")
        self.btn_remove_db.clicked.connect(self._on_remove_library)
        btn_row.addWidget(self.btn_remove_db)

        self.btn_recycle = QPushButton("Send duplicates to Recycle Bin…")
        self.btn_recycle.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        self.btn_recycle.clicked.connect(self._on_recycle)
        btn_row.addWidget(self.btn_recycle)

        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        right_l.addLayout(btn_row)

        splitter.addWidget(right_w)
        splitter.setSizes([260, 690])
        main_layout.addWidget(splitter)

    def _load_groups(self) -> None:
        conn = self.db.new_connection()
        try:
            self.groups = find_duplicate_groups(conn)
        finally:
            conn.close()

        self.group_list.clear()
        total_reclaimable = sum(g.reclaimable_bytes for g in self.groups)
        self.group_count_lbl.setText(
            f"Duplicate Groups ({len(self.groups)}) – {_format_size(total_reclaimable)} reclaimable:"
        )

        for g in self.groups:
            lvl_name = {
                "exact": "Exact duplicate",
                "same_isbn": "Same ISBN",
                "similar": "Similar title/author",
            }.get(g.level, g.level)

            title_preview = g.books[0].get("title") or Path(g.books[0].get("path", "")).stem
            item_text = f"[{lvl_name}] {title_preview}\n{len(g.books)} copies · {_format_size(g.reclaimable_bytes)}"
            item = QListWidgetItem(item_text)
            self.group_list.addItem(item)

        if self.groups:
            self.group_list.setCurrentRow(0)
        else:
            self.group_title_lbl.setText("No duplicates found in your library.")
            self.comp_table.setRowCount(0)
            self.comp_table.setColumnCount(0)

    def _on_group_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.groups):
            return
        self.current_group_idx = row
        group = self.groups[row]
        self.keeper_id = group.suggested_keeper_id
        self._display_group(group)

    def _display_group(self, group: DuplicateGroup) -> None:
        lvl_name = {
            "exact": "Level 1: Exact file content duplicate",
            "same_isbn": "Level 2: Same ISBN (e.g. EPUB vs PDF or reprint)",
            "similar": "Level 3: Similar title and author",
        }.get(group.level, group.level)

        self.group_title_lbl.setText(f"{lvl_name} – {_format_size(group.reclaimable_bytes)} reclaimable")

        books = group.books
        num_books = len(books)
        self.comp_table.setColumnCount(num_books)

        headers = [f"Book #{b['id']}" for b in books]
        self.comp_table.setHorizontalHeaderLabels(headers)

        rows = [
            ("Keeper", lambda b: "Keeper" if b["id"] == self.keeper_id else "Duplicate"),
            ("Title", lambda b: b.get("title") or "—"),
            ("Author", lambda b: b.get("author") or "—"),
            ("Format", lambda b: str(b.get("format", "")).upper()),
            ("Size", lambda b: _format_size(b.get("size_bytes") or 0)),
            ("Pages", lambda b: str(b.get("pages") or "—")),
            ("Year", lambda b: str(b.get("year") or "—")),
            ("ISBN", lambda b: b.get("isbn") or "—"),
            ("Status", lambda b: str(b.get("status") or "Unset")),
            ("Rating", lambda b: f"{b.get('rating')} / 5" if b.get("rating") else "—"),
            ("Path", lambda b: b.get("path") or ""),
        ]

        self.comp_table.setRowCount(len(rows))
        self.comp_table.setVerticalHeaderLabels([r[0] for r in rows])

        for col_idx, b in enumerate(books):
            is_keeper = (b["id"] == self.keeper_id)
            for row_idx, (r_name, extractor) in enumerate(rows):
                val_str = extractor(b)
                item = QTableWidgetItem(val_str)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if is_keeper and row_idx == 0:
                    item.setForeground(Qt.green)
                self.comp_table.setItem(row_idx, col_idx, item)

        self.comp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _on_ignore(self) -> None:
        if not self.groups or self.current_group_idx >= len(self.groups):
            return
        group = self.groups[self.current_group_idx]
        conn = self.db.new_connection()
        try:
            ignore_group(conn, group.group_key)
        finally:
            conn.close()

        self._remove_current_group_from_view()

    def _on_remove_library(self) -> None:
        if not self.groups or self.current_group_idx >= len(self.groups):
            return
        group = self.groups[self.current_group_idx]
        duplicates_to_remove = [b["id"] for b in group.books if b["id"] != self.keeper_id]

        if not duplicates_to_remove:
            return

        reply = QMessageBox.question(
            self,
            "Remove Duplicates from Library",
            f"Remove {len(duplicates_to_remove)} duplicate entries from the library?\n\n"
            "The physical files will NOT be deleted from your disk.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        conn = self.db.new_connection()
        try:
            if self.merge_cb.isChecked() and self.keeper_id:
                merge_book_user_data(conn, self.keeper_id, duplicates_to_remove)
            remove_from_library(conn, duplicates_to_remove)
        finally:
            conn.close()

        self.resolved.emit()
        self._remove_current_group_from_view()

    def _on_recycle(self) -> None:
        if not self.groups or self.current_group_idx >= len(self.groups):
            return
        group = self.groups[self.current_group_idx]
        dup_books = [b for b in group.books if b["id"] != self.keeper_id]
        duplicates_to_remove = [b["id"] for b in dup_books]

        if not duplicates_to_remove:
            return

        paths_preview = "\n".join(f"• {b['path']} ({_format_size(b.get('size_bytes') or 0)})" for b in dup_books)
        total_bytes = sum(b.get("size_bytes") or 0 for b in dup_books)

        msg = (
            f"Are you sure you want to send {len(dup_books)} duplicate file(s) to the Recycle Bin?\n\n"
            f"Total size: {_format_size(total_bytes)}\n\n"
            f"Files:\n{paths_preview}"
        )
        reply = QMessageBox.warning(
            self,
            "Confirm Move to Recycle Bin",
            msg,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        conn = self.db.new_connection()
        try:
            if self.merge_cb.isChecked() and self.keeper_id:
                merge_book_user_data(conn, self.keeper_id, duplicates_to_remove)
            count, errs = send_to_recycle_bin(conn, duplicates_to_remove)
            if errs:
                QMessageBox.warning(self, "Some errors occurred", "\n".join(errs))
        finally:
            conn.close()

        self.resolved.emit()
        self._remove_current_group_from_view()

    def _remove_current_group_from_view(self) -> None:
        del self.groups[self.current_group_idx]
        self.group_list.takeItem(self.current_group_idx)
        total_rec = sum(g.reclaimable_bytes for g in self.groups)
        self.group_count_lbl.setText(
            f"Duplicate Groups ({len(self.groups)}) – {_format_size(total_rec)} reclaimable:"
        )
        if self.groups:
            new_idx = min(self.current_group_idx, len(self.groups) - 1)
            self.group_list.setCurrentRow(new_idx)
        else:
            self.group_title_lbl.setText("All duplicate groups resolved!")
            self.comp_table.setRowCount(0)
            self.comp_table.setColumnCount(0)
