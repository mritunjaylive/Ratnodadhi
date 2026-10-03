"""
drive_settings_page.py – Google Drive and storage cache settings widget.
"""
from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSpinBox,
    QCheckBox,
    QMessageBox,
    QFileDialog,
    QDialog,
    QTextEdit,
)

from booklib.config import DRIVE_CACHE_DIR, CACHE_MARKER_FILE
from booklib.db.repository import Repository
from booklib.drive.auth import TokenStore, disconnect_account
from booklib.drive.cache import clear_drive_cache
from booklib.storage.areas import register_marker
from booklib.storage.policy import StoragePolicy
from booklib.storage.planner import plan_cleanup
from booklib.storage.executor import execute_cleanup
from booklib.storage.usage import get_cache_usage_bytes, count_cached_books
from booklib.ui.drive_connect_dialog import DriveConnectDialog
from booklib.ui.theme import apply_window_rounding

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class DriveSettingsPage(QWidget):
    """Google Drive and Storage management settings panel."""

    accounts_changed = Signal()

    def __init__(self, repo: Repository, token_store: TokenStore | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._repo = repo
        self._token_store = token_store or TokenStore()

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # ── 1. Google Drive Accounts ───────────────────────────────────────────
        acc_group = QGroupBox("Google Drive Accounts")
        acc_layout = QVBoxLayout(acc_group)

        self._acc_table = QTableWidget(0, 4)
        self._acc_table.setHorizontalHeaderLabels(["Account", "Status", "Last Sync", "Actions"])
        self._acc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._acc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._acc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._acc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._acc_table.verticalHeader().setVisible(False)
        self._acc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        acc_layout.addWidget(self._acc_table)

        acc_btn_layout = QHBoxLayout()
        self._connect_btn = QPushButton("Connect Google Drive...")
        self._connect_btn.clicked.connect(self._open_connect_dialog)
        acc_btn_layout.addWidget(self._connect_btn)
        acc_btn_layout.addStretch()
        acc_layout.addLayout(acc_btn_layout)

        layout.addWidget(acc_group)

        # ── 2. Storage & Cache Policy ──────────────────────────────────────────
        cache_group = QGroupBox("Storage & Cache Management")
        cache_layout = QVBoxLayout(cache_group)

        # Settings grid
        keep_recent_layout = QHBoxLayout()
        keep_recent_layout.addWidget(QLabel("Keep last opened books:"))
        self._keep_recent_spin = QSpinBox()
        self._keep_recent_spin.setRange(1, 100)
        self._keep_recent_spin.setValue(10)
        keep_recent_layout.addWidget(self._keep_recent_spin)
        keep_recent_layout.addStretch()
        cache_layout.addLayout(keep_recent_layout)

        self._keep_reading_cb = QCheckBox("Keep books marked Reading (protected from routine cleanup)")
        self._keep_reading_cb.setChecked(True)
        cache_layout.addWidget(self._keep_reading_cb)

        cap_layout = QHBoxLayout()
        cap_layout.addWidget(QLabel("Maximum cache size (GB):"))
        self._cap_spin = QSpinBox()
        self._cap_spin.setRange(1, 500)
        self._cap_spin.setValue(5)
        cap_layout.addWidget(self._cap_spin)
        cap_layout.addStretch()
        cache_layout.addLayout(cap_layout)

        age_layout = QHBoxLayout()
        age_layout.addWidget(QLabel("Remove downloads not opened for (days):"))
        self._age_spin = QSpinBox()
        self._age_spin.setRange(1, 365)
        self._age_spin.setValue(30)
        age_layout.addWidget(self._age_spin)
        age_layout.addStretch()
        cache_layout.addLayout(age_layout)

        free_layout = QHBoxLayout()
        free_layout.addWidget(QLabel("Minimum free disk space (GB):"))
        self._free_spin = QSpinBox()
        self._free_spin.setRange(1, 100)
        self._free_spin.setValue(2)
        free_layout.addWidget(self._free_spin)
        free_layout.addStretch()
        cache_layout.addLayout(free_layout)

        # Stats
        self._usage_label = QLabel("Cache usage: calculating...")
        self._usage_label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        cache_layout.addWidget(self._usage_label)

        # Location
        loc_layout = QHBoxLayout()
        loc_layout.addWidget(QLabel(f"Cache location: {DRIVE_CACHE_DIR}"))
        loc_layout.addStretch()
        cache_layout.addLayout(loc_layout)

        # Action buttons
        clean_btn_layout = QHBoxLayout()
        self._preview_btn = QPushButton("Preview Cleanup")
        self._preview_btn.clicked.connect(self._preview_cleanup)
        clean_btn_layout.addWidget(self._preview_btn)

        self._clean_btn = QPushButton("Clean Now")
        self._clean_btn.clicked.connect(self._run_clean_now)
        clean_btn_layout.addWidget(self._clean_btn)

        self._clear_all_btn = QPushButton("Clear All Cache")
        self._clear_all_btn.clicked.connect(self._clear_all_cache)
        clean_btn_layout.addWidget(self._clear_all_btn)

        clean_btn_layout.addStretch()
        cache_layout.addLayout(clean_btn_layout)

        layout.addWidget(cache_group)
        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        self._load_accounts()
        self._update_usage()

    def _load_accounts(self) -> None:
        accounts = self._repo.list_drive_accounts()
        self._acc_table.setRowCount(len(accounts))
        for row, acc in enumerate(accounts):
            email_item = QTableWidgetItem(acc["email"])
            status_item = QTableWidgetItem(acc.get("status", "ok").upper())
            last_sync = acc.get("last_sync_at") or "Never"
            sync_item = QTableWidgetItem(str(last_sync))

            self._acc_table.setItem(row, 0, email_item)
            self._acc_table.setItem(row, 1, status_item)
            self._acc_table.setItem(row, 2, sync_item)

            action_widget = QWidget()
            h = QHBoxLayout(action_widget)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)

            disc_btn = QPushButton("Disconnect")
            disc_btn.clicked.connect(lambda _, a=acc: self._disconnect_account(a))
            h.addWidget(disc_btn)

            self._acc_table.setCellWidget(row, 3, action_widget)

    def _update_usage(self) -> None:
        size_bytes = get_cache_usage_bytes()
        count = count_cached_books(self._repo)
        cap_bytes = self._cap_spin.value() * 1024 * 1024 * 1024
        self._usage_label.setText(
            f"Cache usage: {_format_size(size_bytes)} / {_format_size(cap_bytes)} "
            f"({count} books cached)"
        )

    def _open_connect_dialog(self) -> None:
        dlg = DriveConnectDialog(self._repo, self._token_store, parent=self)
        if dlg.exec():
            self.refresh()
            self.accounts_changed.emit()

    def _disconnect_account(self, account: dict) -> None:
        email = account["email"]
        reply = QMessageBox.question(
            self, "Disconnect Account",
            f"Disconnect Google Drive account '{email}'?\n\n"
            "Would you also like to remove this account's books from your library and delete its cached downloads?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return

        remove_books = (reply == QMessageBox.StandardButton.Yes)
        disconnect_account(self._repo, account["id"], remove_books=remove_books, token_store=self._token_store)
        self.refresh()
        self.accounts_changed.emit()

    def _get_current_policy(self) -> StoragePolicy:
        return StoragePolicy(
            keep_recent_opened=self._keep_recent_spin.value(),
            keep_reading_books=self._keep_reading_cb.isChecked(),
            size_cap_bytes=self._cap_spin.value() * 1024 * 1024 * 1024,
            max_age_days=self._age_spin.value(),
            min_free_bytes=self._free_spin.value() * 1024 * 1024 * 1024,
        )

    def _preview_cleanup(self) -> None:
        policy = self._get_current_policy()
        plan = plan_cleanup(self._repo, policy, reason="preview")
        dlg = QDialog(self)
        dlg.setWindowTitle("Cleanup Preview")
        dlg.resize(480, 360)
        apply_window_rounding(dlg)
        v = QVBoxLayout(dlg)

        info = QLabel(
            f"<b>Cleanup Plan Preview</b><br>"
            f"Files to delete: {plan.file_count}<br>"
            f"Space to reclaim: {_format_size(plan.total_bytes)}<br>"
        )
        v.addWidget(info)

        details = QTextEdit()
        details.setReadOnly(True)
        if not plan.actions:
            details.setPlainText("No files eligible for cleanup under current policy.")
        else:
            lines = [f"{a.path.name} ({_format_size(a.size_bytes)}) - {a.reason}" for a in plan.actions]
            details.setPlainText("\n".join(lines))
        v.addWidget(details)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        v.addWidget(close_btn)
        dlg.exec()

    def _run_clean_now(self) -> None:
        policy = self._get_current_policy()
        plan = plan_cleanup(self._repo, policy, reason="routine")
        if not plan.actions:
            QMessageBox.information(self, "Clean Up", "No files need to be cleaned up.")
            return

        result = execute_cleanup(self._repo, plan)
        self._update_usage()
        QMessageBox.information(
            self, "Cleanup Complete",
            f"Successfully cleaned up:\n"
            f"• Files deleted: {result.files_deleted}\n"
            f"• Space freed: {_format_size(result.bytes_freed)}"
        )

    def _clear_all_cache(self) -> None:
        reply = QMessageBox.warning(
            self, "Clear All Cache",
            "This will delete all downloaded Drive books from local cache (pinned books will be unpinned and deleted).\n"
            "Are you sure you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cleared_count, cleared_bytes = clear_drive_cache(self._repo)
        self._update_usage()
        QMessageBox.information(
            self, "Cache Cleared",
            f"Cleared {cleared_count} cached books ({_format_size(cleared_bytes)} freed)."
        )
