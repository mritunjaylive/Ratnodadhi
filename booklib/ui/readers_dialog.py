"""
readers_dialog.py – Manage custom readers and default reader per format.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from booklib.db.repository import Repository
from booklib.readers.registry import get_registry

FORMATS = ["pdf", "epub", "mobi", "azw3", "djvu", "cbz", "cbr", "fb2"]


class AddCustomReaderDialog(QDialog):
    """Subdialog to add or edit a custom reader."""

    def __init__(self, reader: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom Reader" if not reader else "Edit Custom Reader")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name = QLineEdit(reader.get("name", "") if reader else "")
        self._name.setPlaceholderText("e.g. SumatraPDF")
        form.addRow("Name:", self._name)

        exe_row = QHBoxLayout()
        self._exe = QLineEdit(reader.get("exe_path", "") if reader else "")
        self._exe.setPlaceholderText("Path to executable")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_exe)
        exe_row.addWidget(self._exe)
        exe_row.addWidget(browse_btn)
        form.addRow("Executable:", exe_row)

        self._formats = QLineEdit(reader.get("formats", "*") if reader else "*")
        self._formats.setPlaceholderText("e.g. pdf, epub, mobi or *")
        form.addRow("Formats:", self._formats)

        self._args = QLineEdit(reader.get("args_template", "{file}") if reader else "{file}")
        self._args.setPlaceholderText("{file}")
        form.addRow("Arguments:", self._args)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Reader Executable", "", "Executables (*.exe);;All Files (*.*)"
        )
        if path:
            self._exe.setText(path)

    def _on_accept(self) -> None:
        if not self._name.text().strip():
            QMessageBox.warning(self, "Validation", "Please enter a reader name.")
            return
        if not self._exe.text().strip():
            QMessageBox.warning(self, "Validation", "Please specify the executable path.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self._name.text().strip(),
            "exe_path": self._exe.text().strip(),
            "formats": self._formats.text().strip() or "*",
            "args_template": self._args.text().strip() or "{file}",
        }


class ReadersDialog(QDialog):
    """Dialog to configure default readers per format and manage custom readers."""

    def __init__(self, repo: Repository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reader Preferences")
        self.setMinimumSize(520, 480)
        self._repo = repo
        self._combos: dict[str, QComboBox] = {}
        self._setup_ui()
        self._load_data()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── Defaults per format ───────────────────────────────────────────────
        def_group = QGroupBox("Default Reader per Format")
        def_form = QFormLayout(def_group)
        def_form.setLabelAlignment(Qt.AlignRight)

        for fmt in FORMATS:
            combo = QComboBox()
            def_form.addRow(f"{fmt.upper()}:", combo)
            self._combos[fmt] = combo

        layout.addWidget(def_group)

        # ── Custom readers ────────────────────────────────────────────────────
        custom_group = QGroupBox("Custom Readers")
        custom_layout = QVBoxLayout(custom_group)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Executable", "Formats", "Args"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        custom_layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Reader…")
        add_btn.clicked.connect(self._on_add)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove)
        refresh_btn = QPushButton("Refresh Detected")
        refresh_btn.clicked.connect(self._on_refresh_detected)

        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(refresh_btn)
        custom_layout.addLayout(btn_row)

        layout.addWidget(custom_group)

        # ── Dialog buttons ────────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self) -> None:
        reg = get_registry()
        reg._repo = self._repo

        # Populate combos for each format
        for fmt, combo in self._combos.items():
            combo.clear()
            combo.addItem("System Default", "system")
            saved_key = self._repo.get_format_default(fmt)

            readers = reg.readers_for(fmt)
            for r in readers:
                combo.addItem(r.name, r.key)

            if saved_key:
                idx = combo.findData(saved_key)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(0)

        # Populate custom readers table
        rows = self._repo.list_custom_readers()
        self._table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            item0 = QTableWidgetItem(row["name"])
            item0.setData(Qt.UserRole, row["id"])
            item1 = QTableWidgetItem(row["exe_path"])
            item2 = QTableWidgetItem(row["formats"])
            item3 = QTableWidgetItem(row["args_template"])
            self._table.setItem(r_idx, 0, item0)
            self._table.setItem(r_idx, 1, item1)
            self._table.setItem(r_idx, 2, item2)
            self._table.setItem(r_idx, 3, item3)

    def _on_add(self) -> None:
        dlg = AddCustomReaderDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self._repo.add_custom_reader(
                name=data["name"],
                exe_path=data["exe_path"],
                formats=data["formats"],
                args_template=data["args_template"],
            )
            get_registry().refresh()
            self._load_data()

    def _on_remove(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        reader_id = item.data(Qt.UserRole)
        name = item.text()
        if QMessageBox.question(
            self, "Confirm", f"Remove custom reader '{name}'?"
        ) == QMessageBox.Yes:
            self._repo.remove_custom_reader(reader_id)
            get_registry().refresh()
            self._load_data()

    def _on_refresh_detected(self) -> None:
        get_registry().refresh()
        self._load_data()
        QMessageBox.information(self, "Refreshed", "Reader detection refreshed.")

    def _on_save(self) -> None:
        for fmt, combo in self._combos.items():
            key = combo.currentData()
            if key:
                self._repo.set_format_default(fmt, key)
        self.accept()
