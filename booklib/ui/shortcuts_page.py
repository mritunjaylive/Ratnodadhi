"""
ui/shortcuts_page.py – Keyboard shortcuts cheat sheet dialog (Ctrl+/) and settings editor.
"""
from __future__ import annotations

import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from booklib.actions import (
    get_all_defs,
    save_shortcut,
    reset_shortcut,
    detect_conflicts,
    ActionDef,
)

logger = logging.getLogger(__name__)


class ShortcutsCheatSheet(QDialog):
    """Read-only shortcuts reference dialog (Ctrl+/)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts — Ratnodadhi")
        self.resize(560, 480)
        self._setup_ui()
        self._populate("")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter shortcuts…")
        self._search.textChanged.connect(self._populate)
        layout.addWidget(self._search)

        # Shortcuts table
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Action", "Menu", "Shortcut"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self._table)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _populate(self, filter_text: str) -> None:
        self._table.setRowCount(0)
        q = filter_text.strip().lower()

        for d in get_all_defs():
            if not d.default_shortcut:
                continue
            if q and q not in f"{d.text} {d.menu} {d.default_shortcut}".lower():
                continue

            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(d.text))
            self._table.setItem(row, 1, QTableWidgetItem(d.menu))

            sc_item = QTableWidgetItem(d.default_shortcut)
            sc_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 2, sc_item)


class ShortcutsEditorDialog(QDialog):
    """Interactive shortcuts configuration dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure Keyboard Shortcuts — Ratnodadhi")
        self.resize(680, 520)
        self._setup_ui()
        self._populate("")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search actions…")
        self._search.textChanged.connect(self._populate)
        top_row.addWidget(self._search)

        reset_all_btn = QPushButton("Reset All to Default")
        reset_all_btn.clicked.connect(self._reset_all)
        top_row.addWidget(reset_all_btn)
        layout.addLayout(top_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Action", "Category", "Shortcut", "Reset"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.accept)
        layout.addWidget(btn_box)

    def _populate(self, filter_text: str) -> None:
        self._table.setRowCount(0)
        q = filter_text.strip().lower()

        from PySide6.QtCore import QSettings
        settings = QSettings("Ratnodadhi", "Ratnodadhi")

        for d in get_all_defs():
            if q and q not in f"{d.text} {d.menu} {d.id}".lower():
                continue

            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(d.text))
            self._table.setItem(row, 1, QTableWidgetItem(d.menu))

            custom = settings.value(f"shortcuts/{d.id}", "")
            current_sc = custom or d.default_shortcut

            seq_edit = QKeySequenceEdit(QKeySequence(current_sc))
            seq_edit.keySequenceChanged.connect(lambda ks, aid=d.id: self._on_seq_changed(aid, ks))
            self._table.setCellWidget(row, 2, seq_edit)

            rst_btn = QPushButton("Reset")
            rst_btn.setStyleSheet("font-size: 11px; padding: 2px 6px;")
            rst_btn.clicked.connect(lambda _, aid=d.id: self._on_reset_one(aid))
            self._table.setCellWidget(row, 3, rst_btn)

    def _on_seq_changed(self, action_id: str, ks: QKeySequence) -> None:
        save_shortcut(action_id, ks.toString())
        conflicts = detect_conflicts()
        if conflicts:
            c_text = "\n".join(f"• {a1} and {a2} both use {seq}" for a1, a2, seq in conflicts)
            QMessageBox.warning(self, "Shortcut Conflict", f"Warning: duplicate shortcut detected:\n\n{c_text}")

    def _on_reset_one(self, action_id: str) -> None:
        reset_shortcut(action_id)
        self._populate(self._search.text())

    def _reset_all(self) -> None:
        if QMessageBox.question(
            self, "Reset All", "Reset all shortcuts to default values?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            for d in get_all_defs():
                reset_shortcut(d.id)
            self._populate(self._search.text())
