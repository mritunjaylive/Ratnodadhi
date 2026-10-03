"""
backup_dialog.py – Backup and restore dialog supporting both Local Folder and Google Drive.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread, QSettings
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QWidget,
    QProgressBar,
    QComboBox,
    QFileDialog,
    QSpinBox,
    QStyle,
)

from booklib.config import DB_PATH, DATA_DIR
from booklib.db.repository import Repository
from booklib.drive.auth import TokenStore, get_credentials
from booklib.drive.client import DriveClient
from booklib.backup.package import build_backup_zip
from booklib.backup.destinations import (
    BackupInfo,
    BackupDestination,
    LocalFolderDestination,
    GoogleDriveDestination,
)
from booklib.backup.restore import verify_and_prepare_restore, apply_staged_restore
from booklib.ui.theme import apply_window_rounding

logger = logging.getLogger(__name__)

_ORG = "Ratnodadhi"
_APP = "Ratnodadhi"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class BackupWorker(QThread):
    finished_success = Signal(str)
    finished_error = Signal(str)

    def __init__(self, dest: BackupDestination, conn, keep_count: int = 10):
        super().__init__()
        self._dest = dest
        self._conn = conn
        self._keep_count = keep_count

    def run(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            build_backup_zip(self._conn, tmp_path)
            backup_id = self._dest.upload(tmp_path, keep_count=self._keep_count)
            self.finished_success.emit(f"Backup created successfully: {backup_id}")
        except Exception as exc:
            logger.exception("Backup failed")
            self.finished_error.emit(str(exc))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass


class ListBackupsWorker(QThread):
    finished_success = Signal(list)
    finished_error = Signal(str)

    def __init__(self, dest: BackupDestination):
        super().__init__()
        self._dest = dest

    def run(self) -> None:
        try:
            items = self._dest.list()
            self.finished_success.emit(items)
        except Exception as exc:
            logger.exception("List backups failed")
            self.finished_error.emit(str(exc))


class BackupDialog(QDialog):
    """Dialog to manage local and cloud library backups and restores."""

    def __init__(
        self,
        repo: Repository,
        token_store: TokenStore | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Library Backup & Restore — Ratnodadhi")
        self.resize(680, 480)
        self.setModal(True)
        apply_window_rounding(self)

        self._repo = repo
        self._conn = getattr(repo, "_conn", None)
        self._token_store = token_store or TokenStore()
        self._drive_client: DriveClient | None = None
        self._backups: list[BackupInfo] = []
        self._active_worker: QThread | None = None

        self._setup_ui()
        self._init_destinations()
        self._refresh_backups()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Destination selector ──────────────────────────────────────────────
        dest_bar = QHBoxLayout()
        dest_bar.addWidget(QLabel("<b>Backup Destination:</b>"))
        self._dest_combo = QComboBox()
        self._dest_combo.addItem(self.style().standardIcon(QStyle.SP_DirIcon), "Local Folder", "local")
        self._dest_combo.currentIndexChanged.connect(self._on_dest_changed)
        dest_bar.addWidget(self._dest_combo)

        self._browse_btn = QPushButton("Browse Folder…")
        self._browse_btn.clicked.connect(self._on_browse_folder)
        dest_bar.addWidget(self._browse_btn)

        dest_bar.addSpacing(16)
        dest_bar.addWidget(QLabel("Keep newest:"))
        self._keep_spin = QSpinBox()
        self._keep_spin.setRange(1, 100)
        self._keep_spin.setValue(10)
        self._keep_spin.valueChanged.connect(self._on_keep_changed)
        dest_bar.addWidget(self._keep_spin)
        dest_bar.addStretch()

        layout.addLayout(dest_bar)

        self._dest_label = QLabel()
        self._dest_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self._dest_label)

        # ── Backups Table ─────────────────────────────────────────────────────
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Name / Date", "Machine", "Books", "Size", "Source"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

        # ── Action Buttons ────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        self._backup_btn = QPushButton("Back Up Now")
        self._backup_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self._backup_btn.clicked.connect(self._start_backup)
        btn_layout.addWidget(self._backup_btn)

        self._restore_btn = QPushButton("Restore Selected…")
        self._restore_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(self._start_restore)
        btn_layout.addWidget(self._restore_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._delete_selected)
        btn_layout.addWidget(self._delete_btn)

        btn_layout.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

    def _init_destinations(self) -> None:
        settings = QSettings(_ORG, _APP)
        self._keep_spin.setValue(int(settings.value("backup/keep_count", 10)))

        # Check Drive accounts
        accounts = self._repo.list_drive_accounts()
        if accounts:
            try:
                creds = get_credentials(accounts[0]["email"], self._token_store)
                self._drive_client = DriveClient(creds)
                self._dest_combo.addItem(self.style().standardIcon(QStyle.SP_DriveNetIcon), "Google Drive", "drive")
            except Exception as exc:
                logger.warning("Could not init Drive client for backup dialog: %s", exc)

        saved_dest = settings.value("backup/destination", "local")
        idx = self._dest_combo.findData(saved_dest)
        if idx >= 0:
            self._dest_combo.setCurrentIndex(idx)
        self._update_dest_display()

    def _get_current_destination(self) -> BackupDestination:
        dest_type = self._dest_combo.currentData()
        if dest_type == "drive" and self._drive_client is not None:
            return GoogleDriveDestination(self._drive_client)

        settings = QSettings(_ORG, _APP)
        folder = settings.value("backup/local_folder", str(DATA_DIR / "backups"))
        return LocalFolderDestination(Path(folder), conn=self._conn)

    def _update_dest_display(self) -> None:
        dest_type = self._dest_combo.currentData()
        if dest_type == "drive":
            self._browse_btn.setVisible(False)
            self._dest_label.setText("Destination: Google Drive (App Data folder)")
        else:
            self._browse_btn.setVisible(True)
            settings = QSettings(_ORG, _APP)
            folder = settings.value("backup/local_folder", str(DATA_DIR / "backups"))
            self._dest_label.setText(f"Folder: {folder}")

    def _on_dest_changed(self) -> None:
        dest_type = self._dest_combo.currentData()
        settings = QSettings(_ORG, _APP)
        settings.setValue("backup/destination", dest_type)
        self._update_dest_display()
        self._refresh_backups()

    def _on_browse_folder(self) -> None:
        settings = QSettings(_ORG, _APP)
        current = settings.value("backup/local_folder", str(DATA_DIR / "backups"))
        chosen = QFileDialog.getExistingDirectory(self, "Select Backup Folder", current)
        if chosen:
            settings.setValue("backup/local_folder", chosen)
            self._update_dest_display()
            self._refresh_backups()

    def _on_keep_changed(self, val: int) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue("backup/keep_count", val)

    def _refresh_backups(self) -> None:
        dest = self._get_current_destination()
        self._progress.setVisible(True)
        self._status_label.setText(f"Loading backups from {dest.name}…")

        worker = ListBackupsWorker(dest)

        def on_done(backups: list[BackupInfo]):
            self._progress.setVisible(False)
            self._backups = backups
            self._status_label.setText(f"Found {len(backups)} backup(s).")
            self._table.setRowCount(len(backups))
            for row, b in enumerate(backups):
                date_str = b.created_at[:19].replace("T", " ") if b.created_at else "-"
                self._table.setItem(row, 0, QTableWidgetItem(f"{b.name} ({date_str})"))
                self._table.setItem(row, 1, QTableWidgetItem(b.computer_name or "-"))
                self._table.setItem(row, 2, QTableWidgetItem(str(b.book_count or "-")))
                self._table.setItem(row, 3, QTableWidgetItem(_format_size(b.size_bytes)))
                self._table.setItem(row, 4, QTableWidgetItem(b.source))

        def on_error(err: str):
            self._progress.setVisible(False)
            self._status_label.setText(f"Error loading backups: {err}")

        worker.finished_success.connect(on_done)
        worker.finished_error.connect(on_error)
        self._active_worker = worker
        worker.start()

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._restore_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)

    def _start_backup(self) -> None:
        dest = self._get_current_destination()
        self._progress.setVisible(True)
        self._backup_btn.setEnabled(False)
        self._status_label.setText("Creating snapshot and storing backup…")

        worker = BackupWorker(dest, self._conn, keep_count=self._keep_spin.value())

        def on_done(msg: str):
            self._progress.setVisible(False)
            self._backup_btn.setEnabled(True)
            self._status_label.setText(msg)
            QMessageBox.information(self, "Backup Complete", msg)
            self._refresh_backups()

        def on_error(err: str):
            self._progress.setVisible(False)
            self._backup_btn.setEnabled(True)
            self._status_label.setText(f"Backup failed: {err}")
            QMessageBox.critical(self, "Backup Failed", err)

        worker.finished_success.connect(on_done)
        worker.finished_error.connect(on_error)
        self._active_worker = worker
        worker.start()

    def _start_restore(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._backups):
            return
        b = self._backups[row]

        dest = self._get_current_destination()

        reply = QMessageBox.warning(
            self,
            "Confirm Restore",
            f"Are you sure you want to restore backup '{b.name}'?\n\n"
            "This will create a safety snapshot of your current library database "
            "and restore the database and custom covers from this backup.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._progress.setVisible(True)
        self._status_label.setText("Preparing and verifying restore…")

        try:
            # Download if needed
            local_zip: Path
            if b.source == "drive":
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    local_zip = Path(tmp.name)
                dest.download(b.id, local_zip)
            elif b.path:
                local_zip = b.path
            else:
                settings = QSettings(_ORG, _APP)
                folder = Path(settings.value("backup/local_folder", str(DATA_DIR / "backups")))
                local_zip = folder / b.id

            staging_dir, safety_copy = verify_and_prepare_restore(
                local_zip,
                target_db_path=DB_PATH,
                conn=self._conn,
            )

            # Apply restore
            apply_staged_restore(staging_dir, DB_PATH)

            self._progress.setVisible(False)
            self._status_label.setText("Restore complete!")
            QMessageBox.information(
                self,
                "Restore Complete",
                f"Library restored successfully from:\n{b.name}\n\n"
                f"A safety copy of your previous database was saved at:\n{safety_copy}\n\n"
                "Please restart the application to reload all restored data.",
            )
            self.accept()

        except Exception as exc:
            self._progress.setVisible(False)
            logger.exception("Restore failed")
            QMessageBox.critical(self, "Restore Failed", str(exc))

    def _delete_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._backups):
            return
        b = self._backups[row]

        if QMessageBox.question(
            self, "Delete Backup",
            f"Delete backup '{b.name}'?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        dest = self._get_current_destination()
        try:
            dest.delete(b.id)
            self._refresh_backups()
        except Exception as exc:
            QMessageBox.warning(self, "Delete Failed", str(exc))
