"""
ui/rename_wizard.py – Rename Files pattern builder and preview launcher dialog.
"""
from __future__ import annotations

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from booklib.organize.template import PRESETS, PRESET_FOLDER
from booklib.organize.planner import RenamePlanner
from booklib.ui.rename_preview import RenamePreviewDialog

logger = logging.getLogger(__name__)


class RenameWizard(QDialog):
    """Wizard to configure file/folder rename patterns and launch the preview table."""

    def __init__(self, repo, conn, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self._conn = conn
        self.setWindowTitle("Rename Files — Pattern Builder")
        self.resize(540, 380)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Scope ─────────────────────────────────────────────────────────────
        scope_group = QGroupBox("Scope")
        scope_layout = QVBoxLayout(scope_group)
        self._scope_all = QRadioButton("All books in library")
        self._scope_all.setChecked(True)
        self._scope_sel = QRadioButton("Selected books only")
        scope_layout.addWidget(self._scope_all)
        scope_layout.addWidget(self._scope_sel)
        layout.addWidget(scope_group)

        # ── Pattern Presets ───────────────────────────────────────────────────
        pattern_group = QGroupBox("File Name Pattern")
        pattern_layout = QVBoxLayout(pattern_group)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        for label, pat in PRESETS.items():
            self._preset_combo.addItem(f"{label} ({pat})", pat)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self._preset_combo)
        pattern_layout.addLayout(preset_row)

        self._pattern_edit = QLineEdit(list(PRESETS.values())[0])
        pattern_layout.addWidget(self._pattern_edit)

        # Token helper buttons
        token_row = QHBoxLayout()
        for tok in ["{author}", "{title}", "{year}", "{series}", "{series_index}", "{isbn}"]:
            btn = QPushButton(tok)
            btn.setStyleSheet("font-size: 11px; padding: 2px 4px;")
            btn.clicked.connect(lambda _, t=tok: self._insert_token(t))
            token_row.addWidget(btn)
        token_row.addStretch()
        pattern_layout.addLayout(token_row)

        layout.addWidget(pattern_group)

        # ── Folder Pattern ────────────────────────────────────────────────────
        folder_group = QGroupBox("Subfolder Pattern (Optional)")
        folder_layout = QVBoxLayout(folder_group)
        self._folder_edit = QLineEdit("")
        self._folder_edit.setPlaceholderText("e.g. {author:sort}/{series} (leave empty to keep current folders)")
        folder_layout.addWidget(self._folder_edit)
        layout.addWidget(folder_group)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox()
        self._preview_btn = btn_box.addButton("Preview Renames…", QDialogButtonBox.AcceptRole)
        self._preview_btn.clicked.connect(self._on_preview)
        btn_box.addButton("Cancel", QDialogButtonBox.RejectRole).clicked.connect(self.reject)
        layout.addWidget(btn_box)

    def _insert_token(self, token: str) -> None:
        self._pattern_edit.insert(token)

    def _on_preset_changed(self) -> None:
        pat = self._preset_combo.currentData()
        if pat:
            self._pattern_edit.setText(pat)

    def _on_preview(self) -> None:
        file_pat = self._pattern_edit.text().strip()
        folder_pat = self._folder_edit.text().strip() or None
        if not file_pat:
            QMessageBox.warning(self, "Invalid Pattern", "Please enter a file name pattern.")
            return

        try:
            # Query books based on scope
            parent_win = self.parent()
            selected_ids = []
            if self._scope_sel.isChecked() and hasattr(parent_win, "_selected_book_ids"):
                selected_ids = parent_win._selected_book_ids()

            if selected_ids:
                placeholders = ",".join("?" * len(selected_ids))
                rows = self._conn.execute(
                    f"SELECT * FROM books WHERE id IN ({placeholders}) AND is_missing = 0 AND source = 'local'",
                    selected_ids,
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM books WHERE is_missing = 0 AND source = 'local'"
                ).fetchall()

            books = [dict(r) for r in rows]
            if not books:
                QMessageBox.information(self, "No Books", "No local books found to rename.")
                return

            planner = RenamePlanner(self._conn)
            preview_rows = planner.plan(books, file_pattern=file_pat, folder_pattern=folder_pat)

            # Open preview dialog
            class _DBWrapper:
                def __init__(self, conn):
                    self.conn = conn

            dlg = RenamePreviewDialog(preview_rows, _DBWrapper(self._conn), parent=self)
            if dlg.exec():
                self.accept()

        except Exception as exc:
            logger.exception("Failed to generate rename plan")
            QMessageBox.critical(self, "Rename Planning Error", str(exc))
