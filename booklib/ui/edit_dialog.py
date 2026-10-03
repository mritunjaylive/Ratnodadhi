"""
edit_dialog.py – single-book and bulk metadata editing dialog.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from booklib.db.repository import BookDetail
from booklib.metadata.filename import validate_isbn


_CURRENT_YEAR = datetime.now().year

EDITABLE_FIELDS = [
    ("title",     "Title",     "text"),
    ("author",    "Author",    "text"),
    ("publisher", "Publisher", "text"),
    ("year",      "Year",      "year"),
    ("edition",   "Edition",   "text"),
    ("isbn",      "ISBN",      "isbn"),
    ("pages",     "Pages",     "pages"),
    ("genre",     "Genre",     "text"),
    ("language",  "Language",  "text"),
]


class EditDialog(QDialog):
    """
    Edit metadata for one book.
    Call `.get_changes()` after exec() to get {field: new_value}.
    """

    def __init__(self, detail: BookDetail, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit – {detail.title or 'Unknown'}")
        self.setMinimumWidth(420)
        self._detail = detail
        self._widgets: dict[str, QWidget] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        for key, label, kind in EDITABLE_FIELDS:
            w = self._make_widget(key, kind)
            self._widgets[key] = w
            form.addRow(f"{label}:", w)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_widget(self, key: str, kind: str) -> QWidget:
        value = getattr(self._detail, key, None)
        if kind == "text":
            w = QLineEdit(str(value) if value is not None else "")
        elif kind == "year":
            w = QSpinBox()
            w.setRange(0, _CURRENT_YEAR)
            w.setSpecialValueText("Unknown")
            w.setValue(value or 0)
        elif kind == "pages":
            w = QSpinBox()
            w.setRange(0, 999999)
            w.setSpecialValueText("Unknown")
            w.setValue(value or 0)
        elif kind == "isbn":
            w = QLineEdit(str(value) if value is not None else "")
        else:
            w = QLineEdit("")
        return w

    def _on_save(self) -> None:
        issues = self._validate()
        if issues:
            reply = QMessageBox.question(
                self, "Validation warnings",
                "\n".join(issues) + "\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.accept()

    def _validate(self) -> list[str]:
        issues: list[str] = []
        year_w = self._widgets.get("year")
        if isinstance(year_w, QSpinBox):
            val = year_w.value()
            if val != 0 and not (1000 <= val <= _CURRENT_YEAR):
                issues.append(f"Year {val} seems implausible.")

        pages_w = self._widgets.get("pages")
        if isinstance(pages_w, QSpinBox):
            val = pages_w.value()
            if val < 0:
                issues.append("Pages cannot be negative.")

        isbn_w = self._widgets.get("isbn")
        if isinstance(isbn_w, QLineEdit):
            raw = isbn_w.text().strip()
            if raw:
                from booklib.metadata.filename import validate_isbn
                if not validate_isbn(raw):
                    issues.append(f"ISBN '{raw}' does not have a valid checksum.")
        return issues

    def get_changes(self) -> dict[str, Any]:
        """Return only the fields that differ from the original."""
        changes: dict[str, Any] = {}
        for key, _, kind in EDITABLE_FIELDS:
            w = self._widgets.get(key)
            if isinstance(w, QLineEdit):
                new = w.text().strip() or None
                old = getattr(self._detail, key, None)
                if new != old:
                    changes[key] = new
            elif isinstance(w, QSpinBox):
                new = w.value() or None
                old = getattr(self._detail, key, None)
                if new != old:
                    changes[key] = new
        return changes


class BulkEditDialog(QDialog):
    """
    Edit shared metadata for multiple books.
    Fields with 'Keep existing' checked are not changed.
    """

    def __init__(self, book_count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Bulk Edit – {book_count} books")
        self.setMinimumWidth(460)
        self._widgets: dict[str, tuple[QWidget, QCheckBox]] = {}
        self._setup_ui(book_count)

    def _setup_ui(self, count: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{count} books selected.</b> Only checked fields will be changed."))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        # Title is disabled in bulk mode
        bulk_fields = [f for f in EDITABLE_FIELDS if f[0] != "title"]
        for key, label, kind in bulk_fields:
            w = self._make_widget(kind)
            cb = QCheckBox("Apply")
            cb.setChecked(False)
            w.setEnabled(False)
            cb.toggled.connect(lambda checked, widget=w: widget.setEnabled(checked))

            from PySide6.QtWidgets import QHBoxLayout
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(cb)
            row_layout.addWidget(w, 1)

            form.addRow(f"{label}:", row)
            self._widgets[key] = (w, cb)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_widget(self, kind: str) -> QWidget:
        if kind == "year":
            w = QSpinBox()
            w.setRange(0, _CURRENT_YEAR)
            w.setSpecialValueText("—")
            return w
        elif kind == "pages":
            w = QSpinBox()
            w.setRange(0, 999999)
            w.setSpecialValueText("—")
            return w
        return QLineEdit()

    def get_changes(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, (w, cb) in self._widgets.items():
            if not cb.isChecked():
                continue
            if isinstance(w, QLineEdit):
                result[key] = w.text().strip() or None
            elif isinstance(w, QSpinBox):
                result[key] = w.value() or None
        return result
