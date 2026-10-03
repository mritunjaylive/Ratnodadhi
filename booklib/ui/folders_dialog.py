"""
folders_dialog.py – "Manage Folders" dialog with Local and Google Drive folder support.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QStyle, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


from booklib.ui.theme import apply_window_rounding


class FoldersDialog(QDialog):
    """Shows the list of library folders with Watch, Sync, and Auto-lookup controls."""

    folder_added = Signal(str)
    drive_folder_requested = Signal()
    folder_removed = Signal(int)   # folder id
    watch_toggled = Signal(int, bool)
    auto_lookup_toggled = Signal(int, bool)

    def __init__(self, folders: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Library Folders")
        self.setMinimumSize(660, 340)
        apply_window_rounding(self)
        self._folders = list(folders)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Library folders (local and cloud):"))

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Folder / Location", "Source", "Watch / Sync", "Auto Lookup"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)

        for f in self._folders:
            self._add_table_row(f)

        layout.addWidget(self._table)

        # Buttons row
        btn_row = QHBoxLayout()
        self._btn_add_local = QPushButton("Add Local Folder…")
        self._btn_add_local.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))

        self._btn_add_drive = QPushButton("Add Drive Folder…")
        self._btn_add_drive.setIcon(self.style().standardIcon(QStyle.SP_DriveNetIcon))

        self._btn_remove = QPushButton("Remove Selected")
        self._btn_remove.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self._btn_remove.setEnabled(False)

        self._btn_add_local.clicked.connect(self._on_add)
        self._btn_add_drive.clicked.connect(self.drive_folder_requested.emit)
        self._btn_remove.clicked.connect(self._on_remove)

        btn_row.addWidget(self._btn_add_local)
        btn_row.addWidget(self._btn_add_drive)
        btn_row.addWidget(self._btn_remove)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._table.itemSelectionChanged.connect(self._update_remove_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def _add_table_row(self, folder: dict) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        source = folder.get("source") or "local"
        is_gdrive = source in ("gdrive", "drive")

        # Path item
        path_str = folder.get("path", "")
        if is_gdrive:
            path_str = f"Google Drive: {folder.get('drive_folder_id', path_str)}"
        path_item = QTableWidgetItem(path_str)
        path_item.setData(Qt.UserRole, folder["id"])
        path_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, 0, path_item)

        # Source item
        source_label = "Google Drive" if is_gdrive else "Local"
        source_item = QTableWidgetItem(source_label)
        source_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, 1, source_item)

        # Watch / Sync checkbox
        cb_watch = QCheckBox()
        if is_gdrive:
            cb_watch.setChecked(bool(folder.get("sync_auto", 1)))
            cb_watch.toggled.connect(lambda chk, fid=folder["id"]: self.watch_toggled.emit(fid, chk))
        else:
            cb_watch.setChecked(bool(folder.get("watch", 0)))
            cb_watch.toggled.connect(lambda chk, fid=folder["id"]: self.watch_toggled.emit(fid, chk))
        w1 = QWidget()
        l1 = QHBoxLayout(w1)
        l1.setAlignment(Qt.AlignCenter)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.addWidget(cb_watch)
        self._table.setCellWidget(row, 2, w1)

        # Auto lookup checkbox
        cb_auto = QCheckBox()
        cb_auto.setChecked(bool(folder.get("auto_lookup", 0)))
        cb_auto.toggled.connect(lambda chk, fid=folder["id"]: self.auto_lookup_toggled.emit(fid, chk))
        w2 = QWidget()
        l2 = QHBoxLayout(w2)
        l2.setAlignment(Qt.AlignCenter)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.addWidget(cb_auto)
        self._table.setCellWidget(row, 3, w2)

    def _update_remove_btn(self) -> None:
        self._btn_remove.setEnabled(len(self._table.selectedItems()) > 0)

    def _on_add(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select a folder to add to the library")
        if path:
            self.folder_added.emit(path)

    def _on_remove(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for r in rows:
            fid = self._table.item(r, 0).data(Qt.UserRole)
            self._table.removeRow(r)
            self.folder_removed.emit(fid)
