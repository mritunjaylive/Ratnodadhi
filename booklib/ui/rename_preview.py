"""
ui/rename_preview.py – Rename files preview dialog.

Shows a table with: Select | Current filename | New filename | Status
Allows editing proposed names, filtering by status, and applying the batch.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTableView, QVBoxLayout,
    QWidget, QLineEdit,
)

from booklib.organize.template import PRESETS
from booklib.organize.planner import RenameRow

logger = logging.getLogger(__name__)

_STATUS_COLORS = {
    "OK":        None,
    "Unchanged": QColor("#888888"),
    "Conflict":  QColor("#cc4444"),
    "Missing":   QColor("#cc8844"),
    "TooLong":   QColor("#cc8844"),
    "NonLocal":  QColor("#888888"),
    "Skipped":   QColor("#888888"),
    "Guessed":   QColor("#ccaa00"),
}

_COLS = ["Select", "Current name", "New name", "Status"]


class _RenameModel(QAbstractTableModel):
    def __init__(self, rows: list[RenameRow], parent=None) -> None:
        super().__init__(parent)
        self._rows = rows
        self._checked: list[bool] = [r.checked for r in rows]

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(_COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _COLS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return None
            if col == 1:
                return Path(row.old_path).name
            if col == 2:
                return Path(row.new_path).name if row.new_path else "—"
            if col == 3:
                return row.status

        if role == Qt.CheckStateRole and col == 0:
            return Qt.Checked if self._checked[index.row()] else Qt.Unchecked

        if role == Qt.ForegroundRole and col == 3:
            color = _STATUS_COLORS.get(row.status)
            return color

        if role == Qt.ToolTipRole:
            if col == 1:
                return row.old_path
            if col == 2:
                return row.new_path
            if row.reason:
                return row.reason

        return None

    def flags(self, index: QModelIndex):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            return base | Qt.ItemIsUserCheckable
        if index.column() == 2 and self._rows[index.row()].status == "OK":
            return base | Qt.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: Any, role=Qt.EditRole) -> bool:
        if role == Qt.CheckStateRole and index.column() == 0:
            self._checked[index.row()] = (value == Qt.Checked)
            self.dataChanged.emit(index, index)
            return True
        if role == Qt.EditRole and index.column() == 2:
            # Allow editing proposed new name
            new_name = str(value).strip()
            if new_name:
                row = self._rows[index.row()]
                parent_dir = Path(row.new_path).parent if row.new_path else Path(row.old_path).parent
                row.new_path = str(parent_dir / new_name)
                self.dataChanged.emit(index, index)
            return True
        return False

    def ok_rows(self) -> list[RenameRow]:
        """Return checked OK rows."""
        return [
            self._rows[i] for i, checked in enumerate(self._checked)
            if checked and self._rows[i].status == "OK"
        ]

    def select_only_ok(self) -> None:
        for i, row in enumerate(self._rows):
            self._checked[i] = (row.status == "OK")
        self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, 0))


class RenamePreviewDialog(QDialog):
    """
    Preview and apply a rename batch.

    Emits batch_done(batch_id) when rename was applied successfully.
    """

    batch_done = Signal(str)   # batch_id

    def __init__(self, rows: list[RenameRow], db, parent=None) -> None:
        super().__init__(parent)
        self._rows = rows
        self._db = db
        self._batch_id: str = ""
        self.setWindowTitle("Rename files")
        self.setMinimumSize(900, 520)
        from booklib.ui.theme import apply_window_rounding
        apply_window_rounding(self)
        self._setup_ui()
        self._refresh_summary()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── Status filter ─────────────────────────────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Show:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(["All", "OK", "Conflict", "Missing", "Unchanged", "Guessed", "Skipped"])
        self._status_filter.currentTextChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._status_filter)
        filter_bar.addStretch()

        select_ok_btn = QPushButton("Select only OK")
        select_ok_btn.clicked.connect(self._on_select_ok)
        filter_bar.addWidget(select_ok_btn)
        layout.addLayout(filter_bar)

        # ── Table ─────────────────────────────────────────────────────────────
        self._model = _RenameModel(self._rows)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.verticalHeader().hide()
        layout.addWidget(self._table)

        # ── Summary bar ───────────────────────────────────────────────────────
        self._summary_label = QLabel()
        self._summary_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self._summary_label)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox()
        self._apply_btn = btn_box.addButton("Apply", QDialogButtonBox.AcceptRole)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_box.addButton("Cancel", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        layout.addWidget(btn_box)

    def _refresh_summary(self) -> None:
        ok = sum(1 for r in self._rows if r.status == "OK")
        conflict = sum(1 for r in self._rows if r.status == "Conflict")
        skipped = sum(1 for r in self._rows if r.status in ("Skipped", "NonLocal", "Missing", "TooLong"))
        self._summary_label.setText(
            f"{len(self._rows)} total · {ok} OK · {conflict} conflict(s) · {skipped} skipped"
        )

    def _apply_filter(self, status: str) -> None:
        for row_idx in range(len(self._rows)):
            should_show = status == "All" or self._rows[row_idx].status == status
            self._table.setRowHidden(row_idx, not should_show)

    def _on_select_ok(self) -> None:
        self._model.select_only_ok()

    def _on_apply(self) -> None:
        ok_rows = self._model.ok_rows()
        if not ok_rows:
            QMessageBox.information(self, "Nothing to rename", "No rows are selected with OK status.")
            return

        if QMessageBox.question(
            self, "Rename files",
            f"Rename {len(ok_rows)} file(s)? This cannot be undone without using "
            "Library → Undo rename batch.",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        try:
            from booklib.organize.executor import RenameExecutor
            conn = self._db.conn
            executor = RenameExecutor(conn, remove_empty_dirs=False)
            summary = executor.execute(ok_rows, file_pattern="custom")
            batch_id = summary.get("batch_id", "")
            renamed = summary.get("renamed", 0)
            failed = summary.get("failed", 0)

            msg = f"Renamed {renamed} file(s)."
            if failed:
                msg += f"\n{failed} file(s) failed (see log for details)."
            QMessageBox.information(self, "Rename complete", msg)

            if batch_id:
                self.batch_done.emit(batch_id)
            self.accept()
        except Exception as exc:
            logger.error("Rename apply failed: %s", exc)
            QMessageBox.critical(self, "Error", f"Rename failed: {exc}")
