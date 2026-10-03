"""
reader/ui/notes_panel.py – In-reader annotations & notes panel with filters and export.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from booklib.reader.annotations import (
    delete_annotation,
    export_annotated_pdf,
    export_csv,
    export_html,
    export_json,
    export_markdown,
    list_annotations,
    update_annotation,
)
from booklib.reader.backend import Locator


class NotesPanel(QWidget):
    """Panel in the reader displaying highlights and notes for the active book."""

    annotation_jump = Signal(object)  # Locator
    annotations_changed = Signal()

    def __init__(self, conn_supplier, book_id: int | None = None, file_path: str = "", parent=None) -> None:
        super().__init__(parent)
        self._conn_supplier = conn_supplier
        self._book_id = book_id
        self._file_path = file_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Filter bar
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Color:", self))
        self._color_filter = QComboBox(self)
        self._color_filter.addItems(["All", "Yellow", "Green", "Blue", "Pink", "Orange"])
        self._color_filter.currentTextChanged.connect(lambda _: self.reload())
        filter_layout.addWidget(self._color_filter, 1)

        self._btn_export = QPushButton("Export…", self)
        self._btn_export.clicked.connect(self._show_export_menu)
        filter_layout.addWidget(self._btn_export)

        layout.addLayout(filter_layout)

        # List
        self._list = QListWidget(self)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)

        self._empty_label = QLabel("No highlights or notes in this book yet.\nSelect text and press H to highlight.", self)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: gray; padding: 20px;")
        layout.addWidget(self._empty_label)

        # Buttons
        btn_layout = QHBoxLayout()
        self._btn_jump = QPushButton("Jump", self)
        self._btn_jump.clicked.connect(self._on_jump)
        btn_layout.addWidget(self._btn_jump)

        self._btn_edit_note = QPushButton("Edit Note", self)
        self._btn_edit_note.clicked.connect(self._on_edit_note)
        btn_layout.addWidget(self._btn_edit_note)

        self._btn_delete = QPushButton("Delete", self)
        self._btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self._btn_delete)

        layout.addLayout(btn_layout)
        self.reload()

    def set_book(self, book_id: int | None, file_path: str = "") -> None:
        self._book_id = book_id
        self._file_path = file_path
        self.reload()

    def reload(self) -> None:
        self._list.clear()
        if self._book_id is None:
            self._list.hide()
            self._empty_label.show()
            return

        conn = self._conn_supplier()
        if not conn:
            return

        color = self._color_filter.currentText().lower()
        color_arg = None if color == "all" else color
        annots = list_annotations(conn, book_id=self._book_id, color=color_arg)

        if not annots:
            self._list.hide()
            self._empty_label.show()
            return

        self._empty_label.hide()
        self._list.show()

        for a in annots:
            loc = a.get("locator_obj") or Locator.from_json(a.get("locator", "{}"))
            p = f"p. {(loc.page or 0) + 1}" if loc.page is not None else ""
            note_str = f"\n   Note: \"{a['note']}\"" if a.get("note") else ""
            item = QListWidgetItem(f"[{a['color'].upper()}] \"{a['quote']}\" ({p}){note_str}")
            item.setData(Qt.UserRole, a)
            self._list.addItem(item)

    def _selected_item(self) -> dict[str, Any] | None:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_jump(self) -> None:
        a = self._selected_item()
        if a:
            self.annotation_jump.emit(a["locator_obj"])

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._on_jump()

    def _on_edit_note(self) -> None:
        a = self._selected_item()
        if not a:
            return
        curr_note = a.get("note") or ""
        new_note, ok = QInputDialog.getMultiLineText(self, "Edit Note", "Note for this highlight:", text=curr_note)
        if ok:
            conn = self._conn_supplier()
            if conn:
                update_annotation(conn, a["id"], note=new_note.strip())
                self.reload()
                self.annotations_changed.emit()

    def _on_delete(self) -> None:
        a = self._selected_item()
        if not a:
            return
        if QMessageBox.question(self, "Delete Highlight", "Delete this highlight?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            conn = self._conn_supplier()
            if conn:
                delete_annotation(conn, a["id"])
                self.reload()
                self.annotations_changed.emit()

    def _show_export_menu(self) -> None:
        conn = self._conn_supplier()
        if not conn or not self._book_id:
            return

        annots = list_annotations(conn, book_id=self._book_id)
        if not annots:
            QMessageBox.information(self, "No Highlights", "There are no highlights to export.")
            return

        menu = QMenu(self)
        act_md = menu.addAction("Export as Markdown (.md)")
        act_html = menu.addAction("Export as HTML (.html)")
        act_csv = menu.addAction("Export as CSV (.csv)")
        act_json = menu.addAction("Export as JSON (.json)")

        if self._file_path.lower().endswith(".pdf"):
            act_pdf = menu.addAction("Export Annotated PDF copy (.pdf)")
        else:
            act_pdf = None

        action = menu.exec(self._btn_export.mapToGlobal(self._btn_export.rect().bottomLeft()))
        if not action:
            return

        title = annots[0].get("book_title", "Highlights")
        author = annots[0].get("book_author", "")

        if action == act_md:
            path, _ = QFileDialog.getSaveFileName(self, "Save Markdown", f"{title} - Highlights.md", "Markdown (*.md)")
            if path:
                Path(path).write_text(export_markdown(annots, title, author), encoding="utf-8")
        elif action == act_html:
            path, _ = QFileDialog.getSaveFileName(self, "Save HTML", f"{title} - Highlights.html", "HTML (*.html)")
            if path:
                Path(path).write_text(export_html(annots, title, author), encoding="utf-8")
        elif action == act_csv:
            path, _ = QFileDialog.getSaveFileName(self, "Save CSV", f"{title} - Highlights.csv", "CSV (*.csv)")
            if path:
                Path(path).write_text(export_csv(annots), encoding="utf-8")
        elif action == act_json:
            path, _ = QFileDialog.getSaveFileName(self, "Save JSON", f"{title} - Highlights.json", "JSON (*.json)")
            if path:
                Path(path).write_text(export_json(annots), encoding="utf-8")
        elif act_pdf and action == act_pdf:
            path, _ = QFileDialog.getSaveFileName(self, "Save Annotated PDF", f"{title} - Annotated.pdf", "PDF (*.pdf)")
            if path:
                ok = export_annotated_pdf(self._file_path, path, annots)
                if ok:
                    QMessageBox.information(self, "Export Complete", f"Annotated PDF saved to:\n{path}")
                else:
                    QMessageBox.warning(self, "Export Failed", "Could not export annotated PDF.")
