"""
drive_folder_picker.py – Lazy tree folder picker for Google Drive.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QCheckBox,
    QComboBox,
    QMessageBox,
    QWidget,
    QProgressBar,
)

from booklib.db.repository import Repository
from booklib.drive.auth import TokenStore, get_credentials
from booklib.drive.client import DriveClient
from booklib.ui.theme import apply_window_rounding

logger = logging.getLogger(__name__)


@dataclass
class DriveFolderSelection:
    account_id: int
    folder_id: str
    folder_name: str
    include_subfolders: bool
    sync_auto: bool
    deep_index: bool
    create_collections: bool


class LoadFoldersWorker(QThread):
    finished_folders = Signal(list)  # list[dict]
    finished_error = Signal(str)

    def __init__(self, client: DriveClient, parent_id: str | None, is_shared: bool = False):
        super().__init__()
        self._client = client
        self._parent_id = parent_id
        self._is_shared = is_shared

    def run(self) -> None:
        try:
            if self._is_shared:
                query = "mimeType = 'application/vnd.google-apps.folder' and sharedWithMe = true and trashed = false"
            else:
                pid = self._parent_id or "root"
                query = f"mimeType = 'application/vnd.google-apps.folder' and '{pid}' in parents and trashed = false"

            folders = self._client.list_files(
                query=query,
                fields="nextPageToken, files(id, name, mimeType)",
                page_size=100,
            )
            folders.sort(key=lambda f: f.name.lower())
            self.finished_folders.emit([{"id": f.id, "name": f.name} for f in folders])
        except Exception as exc:
            logger.exception("Failed to load drive folders")
            self.finished_error.emit(str(exc))


class DriveFolderPicker(QDialog):
    """Dialog to select a Google Drive folder for indexing."""

    folder_selected = Signal(object)  # DriveFolderSelection

    def __init__(self, repo: Repository, token_store: TokenStore | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Google Drive Folder")
        self.resize(520, 560)
        self.setModal(True)
        apply_window_rounding(self)

        self._repo = repo
        self._token_store = token_store or TokenStore()
        self._accounts: list[dict] = []
        self._client: DriveClient | None = None
        self._loading_threads: list[LoadFoldersWorker] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Account selection
        acc_layout = QHBoxLayout()
        acc_layout.addWidget(QLabel("Account:"))
        self._account_combo = QComboBox()
        self._account_combo.currentIndexChanged.connect(self._on_account_changed)
        acc_layout.addWidget(self._account_combo, 1)
        layout.addLayout(acc_layout)

        # Folder Tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Folder"])
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._tree, 1)

        self._loading_bar = QProgressBar()
        self._loading_bar.setRange(0, 0)
        self._loading_bar.setVisible(False)
        layout.addWidget(self._loading_bar)

        # Selected info
        self._info_label = QLabel("Selected: None")
        self._info_label.setStyleSheet("color: #666; font-weight: bold;")
        layout.addWidget(self._info_label)

        # Options
        self._subfolders_cb = QCheckBox("Include subfolders")
        self._subfolders_cb.setChecked(True)
        layout.addWidget(self._subfolders_cb)

        self._sync_auto_cb = QCheckBox("Sync automatically (every 15 min)")
        self._sync_auto_cb.setChecked(True)
        layout.addWidget(self._sync_auto_cb)

        self._deep_index_cb = QCheckBox("Read metadata from files after indexing (deep index)")
        self._deep_index_cb.setChecked(False)
        layout.addWidget(self._deep_index_cb)

        self._collections_cb = QCheckBox("Create collections from folder structure")
        self._collections_cb.setChecked(False)
        layout.addWidget(self._collections_cb)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        self._add_btn = QPushButton("Add Folder")
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add_clicked)
        btn_layout.addWidget(self._add_btn)

        layout.addLayout(btn_layout)

        self._load_accounts()

    def _load_accounts(self) -> None:
        self._accounts = self._repo.list_drive_accounts()
        self._account_combo.clear()
        for acc in self._accounts:
            label = acc["email"]
            if acc.get("display_name"):
                label += f" ({acc['display_name']})"
            self._account_combo.addItem(label, acc["id"])

        if not self._accounts:
            self._info_label.setText("No connected Google Drive accounts found.")
            self._add_btn.setEnabled(False)

    def _on_account_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._accounts):
            return
        account = self._accounts[idx]
        email = account["email"]
        try:
            creds = get_credentials(email, self._token_store)
            self._client = DriveClient(creds)
            self._populate_root()
        except Exception as exc:
            logger.exception("Failed to connect client for %s", email)
            QMessageBox.critical(self, "Error", f"Failed to authenticate account:\n{exc}")

    def _populate_root(self) -> None:
        self._tree.clear()

        # My Drive item
        my_drive = QTreeWidgetItem(self._tree, ["My Drive"])
        my_drive.setData(0, Qt.ItemDataRole.UserRole, {"id": "root", "name": "My Drive", "loaded": False})
        # Add a dummy child to show expand arrow
        my_drive.addChild(QTreeWidgetItem(["Loading..."]))

        # Shared with me item
        shared = QTreeWidgetItem(self._tree, ["Shared with me"])
        shared.setData(0, Qt.ItemDataRole.UserRole, {"id": "__shared__", "name": "Shared with me", "loaded": False})
        shared.addChild(QTreeWidgetItem(["Loading..."]))

        my_drive.setExpanded(True)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("loaded"):
            return

        if not self._client:
            return

        # Clear placeholder
        item.takeChildren()

        folder_id = data["id"]
        is_shared = (folder_id == "__shared__")

        self._loading_bar.setVisible(True)
        worker = LoadFoldersWorker(self._client, folder_id if not is_shared else None, is_shared=is_shared)

        def on_done(folders: list[dict]):
            self._loading_bar.setVisible(False)
            data["loaded"] = True
            for f in folders:
                child = QTreeWidgetItem(item, [f["name"]])
                child.setData(0, Qt.ItemDataRole.UserRole, {"id": f["id"], "name": f["name"], "loaded": False})
                child.addChild(QTreeWidgetItem(["Loading..."]))

        def on_error(err: str):
            self._loading_bar.setVisible(False)
            err_item = QTreeWidgetItem(item, [f"Error: {err}"])
            err_item.setForeground(0, Qt.GlobalColor.red)

        worker.finished_folders.connect(on_done)
        worker.finished_error.connect(on_error)
        self._loading_threads.append(worker)
        worker.start()

    def _on_selection_changed(self) -> None:
        selected_items = self._tree.selectedItems()
        if not selected_items:
            self._info_label.setText("Selected: None")
            self._add_btn.setEnabled(False)
            return

        item = selected_items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data["id"] == "__shared__":
            self._info_label.setText("Select a folder")
            self._add_btn.setEnabled(False)
            return

        self._info_label.setText(f"Selected: {data['name']}")
        self._add_btn.setEnabled(True)

    def _on_add_clicked(self) -> None:
        idx = self._account_combo.currentIndex()
        if idx < 0 or idx >= len(self._accounts):
            return
        account = self._accounts[idx]
        account_id = account["id"]

        selected_items = self._tree.selectedItems()
        if not selected_items:
            return
        data = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        folder_id = data["id"]
        folder_name = data["name"]

        # Check existing folders to prevent overlap
        existing = self._repo.list_folders()
        for f in existing:
            if f.get("source") == "gdrive" and f.get("drive_folder_id") == folder_id:
                QMessageBox.warning(
                    self, "Duplicate Folder",
                    f"The folder '{folder_name}' has already been added to the library."
                )
                return

        selection = DriveFolderSelection(
            account_id=account_id,
            folder_id=folder_id,
            folder_name=folder_name,
            include_subfolders=self._subfolders_cb.isChecked(),
            sync_auto=self._sync_auto_cb.isChecked(),
            deep_index=self._deep_index_cb.isChecked(),
            create_collections=self._collections_cb.isChecked(),
        )

        self.folder_selected.emit(selection)
        self.accept()
