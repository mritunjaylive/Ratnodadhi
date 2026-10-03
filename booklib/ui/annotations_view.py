"""
ui/annotations_view.py – Highlights & Notes library view across all books.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from booklib.reader.annotations import (
    delete_annotation,
    export_csv,
    export_html,
    export_json,
    export_markdown,
    list_annotations,
)
from booklib.reader.backend import Locator
from booklib.reader.manager import get_reader_manager


class AnnotationsView(QWidget):
    """Library-wide view of all highlights and notes across all books."""

    def __init__(self, conn_supplier, parent=None) -> None:
        super().__init__(parent)
        self._conn_supplier = conn_supplier

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Header & Filters ──────────────────────────────────────────────────
        title = QLabel("Highlights & Notes", self)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        filter_bar = QHBoxLayout()

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("Search quotes and notes…")
        self._search_input.textChanged.connect(lambda _: self.reload())
        filter_bar.addWidget(self._search_input, 2)

        filter_bar.addWidget(QLabel("Color:", self))
        self._color_filter = QComboBox(self)
        self._color_filter.addItems(["All", "Yellow", "Green", "Blue", "Pink", "Orange"])
        self._color_filter.currentTextChanged.connect(lambda _: self.reload())
        filter_bar.addWidget(self._color_filter)

        filter_bar.addWidget(QLabel("Kind:", self))
        self._kind_filter = QComboBox(self)
        self._kind_filter.addItems(["All", "Highlight", "Underline", "Note"])
        self._kind_filter.currentTextChanged.connect(lambda _: self.reload())
        filter_bar.addWidget(self._kind_filter)

        filter_bar.addStretch()

        self._btn_jump = QPushButton("Open in Reader", self)
        self._btn_jump.clicked.connect(self._on_open_in_reader)
        filter_bar.addWidget(self._btn_jump)

        self._btn_export = QPushButton("Export All…", self)
        self._btn_export.clicked.connect(self._on_export)
        filter_bar.addWidget(self._btn_export)

        layout.addLayout(filter_bar)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(["Book", "Quote", "Note", "Color", "Page", "Date"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.itemDoubleClicked.connect(lambda _: self._on_open_in_reader())
        layout.addWidget(self._table)

        self._annotations: list[dict[str, Any]] = []

    def reload(self) -> None:
        conn = self._conn_supplier()
        if not conn:
            return

        query = self._search_input.text().strip() or None
        color = self._color_filter.currentText().lower()
        color_arg = None if color == "all" else color
        kind = self._kind_filter.currentText().lower()
        kind_arg = None if kind == "all" else kind

        self._annotations = list_annotations(
            conn,
            query=query,
            color=color_arg,
            kind=kind_arg,
        )

        self._table.setRowCount(len(self._annotations))
        for row, a in enumerate(self._annotations):
            loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
            p = f"{loc.page + 1}" if loc.page is not None else ""

            self._table.setItem(row, 0, QTableWidgetItem(f"{a.get('book_title', '')}"))
            self._table.setItem(row, 1, QTableWidgetItem(a.get("quote", "")))
            self._table.setItem(row, 2, QTableWidgetItem(a.get("note", "") or ""))
            self._table.setItem(row, 3, QTableWidgetItem(a.get("color", "").upper()))
            self._table.setItem(row, 4, QTableWidgetItem(p))
            self._table.setItem(row, 5, QTableWidgetItem((a.get("created_at") or "")[:10]))

    def _selected_annotation(self) -> dict[str, Any] | None:
        row = self._table.currentRow()
        if 0 <= row < len(self._annotations):
            return self._annotations[row]
        return None

    def _on_open_in_reader(self) -> None:
        a = self._selected_annotation()
        if not a:
            return
        book_id = a["book_id"]
        loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
        mgr = get_reader_manager(self._conn_supplier)
        mgr.open_book(book_id, locator=loc, highlight_query=a.get("quote"))

    def _on_export(self) -> None:
        if not self._annotations:
            QMessageBox.information(self, "No Annotations", "There are no annotations to export.")
            return

        menu = QMenu(self)
        act_md = menu.addAction("Export as Markdown (.md)")
        act_html = menu.addAction("Export as HTML (.html)")
        act_csv = menu.addAction("Export as CSV (.csv)")
        act_json = menu.addAction("Export as JSON (.json)")

        action = menu.exec(self._btn_export.mapToGlobal(self._btn_export.rect().bottomLeft()))
        if not action:
            return

        if action == act_md:
            path, _ = QFileDialog.getSaveFileName(self, "Save Markdown", "All Highlights.md", "Markdown (*.md)")
            if path:
                Path(path).write_text(export_markdown(self._annotations, "Library Highlights"), encoding="utf-8")
        elif action == act_html:
            path, _ = QFileDialog.getSaveFileName(self, "Save HTML", "All Highlights.html", "HTML (*.html)")
            if path:
                Path(path).write_text(export_html(self._annotations, "Library Highlights"), encoding="utf-8")
        elif action == act_csv:
            path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "All Highlights.csv", "CSV (*.csv)")
            if path:
                Path(path).write_text(export_csv(self._annotations), encoding="utf-8")
        elif action == act_json:
            path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "All Highlights.json", "JSON (*.json)")
            if path:
                Path(path).write_text(export_json(self._annotations), encoding="utf-8")
