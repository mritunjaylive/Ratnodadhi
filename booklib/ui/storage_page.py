"""
ui/storage_page.py – Storage settings page displaying storage areas, disk space, and cleanup tools.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from booklib.config import DATA_DIR, COVERS_DIR, DRIVE_CACHE_DIR
from booklib.storage.areas import get_storage_areas, StorageArea
from booklib.storage.policy import StoragePolicy, load_storage_policy, save_storage_policy
from booklib.storage.planner import plan_cleanup
from booklib.storage.executor import execute_cleanup

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


class StoragePage(QWidget):
    """Storage overview and management panel."""

    def __init__(self, conn, repo=None, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._repo = repo
        self._areas = get_storage_areas()
        self._setup_ui()
        self._refresh_all()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── Header Banner (Disk Space Overview) ───────────────────────────────
        header_box = QHBoxLayout()
        self._drive_space_label = QLabel()
        self._drive_space_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        header_box.addWidget(self._drive_space_label)

        header_box.addStretch()
        open_data_btn = QPushButton("Open Data Folder")
        open_data_btn.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        open_data_btn.clicked.connect(self._open_data_dir)
        header_box.addWidget(open_data_btn)
        layout.addLayout(header_box)

        # Low-space warning banner (hidden by default)
        self._low_space_banner = QLabel()
        self._low_space_banner.setStyleSheet(
            "padding: 8px; border-radius: 4px; background: rgba(239, 68, 68, 0.15); color: #dc2626; font-weight: bold;"
        )
        self._low_space_banner.setVisible(False)
        layout.addWidget(self._low_space_banner)

        # ── Areas Table ───────────────────────────────────────────────────────
        areas_group = QGroupBox("Storage Areas")
        ag_layout = QVBoxLayout(areas_group)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Area", "Used", "Limit", "Policy", "Actions"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        ag_layout.addWidget(self._table)
        layout.addWidget(areas_group)

        # ── Policy & Retention Controls ───────────────────────────────────────
        policy_group = QGroupBox("Cache Policy & Retention")
        p_layout = QVBoxLayout(policy_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Keep last opened books:"))
        self._keep_recent_spin = QSpinBox()
        self._keep_recent_spin.setRange(1, 100)
        row1.addWidget(self._keep_recent_spin)

        self._keep_reading_check = QCheckBox("Keep books marked 'Reading'")
        row1.addWidget(self._keep_reading_check)
        row1.addStretch()
        p_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Cache limit (GB):"))
        self._limit_gb_spin = QSpinBox()
        self._limit_gb_spin.setRange(1, 100)
        row2.addWidget(self._limit_gb_spin)

        row2.addWidget(QLabel("Minimum free disk space (GB):"))
        self._min_free_spin = QSpinBox()
        self._min_free_spin.setRange(1, 50)
        row2.addWidget(self._min_free_spin)
        row2.addStretch()
        p_layout.addLayout(row2)

        save_policy_btn = QPushButton("Save Settings")
        save_policy_btn.clicked.connect(self._save_policy)
        p_layout.addWidget(save_policy_btn)

        layout.addWidget(policy_group)

        # ── Cleanup Actions Bar ───────────────────────────────────────────────
        btn_bar = QHBoxLayout()
        preview_btn = QPushButton("Preview Cleanup")
        preview_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogInfoView))
        preview_btn.clicked.connect(self._preview_cleanup)
        btn_bar.addWidget(preview_btn)

        clean_now_btn = QPushButton("Clean Now")
        clean_now_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        clean_now_btn.clicked.connect(self._clean_now)
        btn_bar.addWidget(clean_now_btn)

        clear_regen_btn = QPushButton("Clear Regenerable Data…")
        clear_regen_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        clear_regen_btn.setStyleSheet("color: #dc2626;")
        clear_regen_btn.clicked.connect(self._clear_regenerable)
        btn_bar.addWidget(clear_regen_btn)

        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        layout.addStretch()

    def _open_data_dir(self) -> None:
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))

    def _open_folder(self, path: Path) -> None:
        from PySide6.QtCore import QUrl
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _refresh_all(self) -> None:
        # Measure drive free space
        try:
            usage = shutil.disk_usage(str(DATA_DIR))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            self._drive_space_label.setText(
                f"Drive: {free_gb:.1f} GB free of {total_gb:.1f} GB"
            )
            if free_gb < 2.0:
                self._low_space_banner.setText(f"Low disk space: only {free_gb:.1f} GB available on app drive.")
                self._low_space_banner.setVisible(True)
            else:
                self._low_space_banner.setVisible(False)
        except Exception:
            pass

        # Populate areas table
        policy = load_storage_policy(self._conn) if self._conn else StoragePolicy()
        self._keep_recent_spin.setValue(policy.keep_recent_books)
        self._keep_reading_check.setChecked(policy.keep_reading_books)
        self._limit_gb_spin.setValue(int(policy.cache_limit_bytes / (1024 ** 3)))
        self._min_free_spin.setValue(int(policy.min_free_bytes / (1024 ** 3)))

        self._table.setRowCount(len(self._areas))
        for row, (key, area) in enumerate(self._areas.items()):
            used_bytes = area.usage()
            limit_str = _format_size(area.limit_bytes) if area.limit_bytes else "—"
            policy_str = {
                "drive_downloads": "last 10 + Reading, 30 days",
                "covers": "orphans swept",
                "safety_snapshots": "newest 5 or 14 days",
                "backups": "keep newest 10",
                "logs": "rotating (25 MB)",
            }.get(key, area.kind)

            self._table.setItem(row, 0, QTableWidgetItem(area.label))
            self._table.setItem(row, 1, QTableWidgetItem(_format_size(used_bytes)))
            self._table.setItem(row, 2, QTableWidgetItem(limit_str))
            self._table.setItem(row, 3, QTableWidgetItem(policy_str))

            # Action widget
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(0, 0, 0, 0)
            open_btn = QPushButton("Open")
            open_btn.setStyleSheet("font-size: 11px; padding: 2px 6px;")
            open_btn.clicked.connect(lambda _, p=area.root: self._open_folder(p))
            act_layout.addWidget(open_btn)
            self._table.setCellWidget(row, 4, act_widget)

    def _save_policy(self) -> None:
        policy = StoragePolicy(
            keep_recent_books=self._keep_recent_spin.value(),
            keep_reading_books=self._keep_reading_check.isChecked(),
            cache_limit_bytes=self._limit_gb_spin.value() * 1024 * 1024 * 1024,
            min_free_bytes=self._min_free_spin.value() * 1024 * 1024 * 1024,
        )
        if self._conn:
            save_storage_policy(self._conn, policy)
        QMessageBox.information(self, "Settings Saved", "Storage cache policy updated.")

    def _preview_cleanup(self) -> None:
        if not self._conn:
            return
        plan = plan_cleanup(self._conn, reason="user_preview")
        if not plan.actions:
            QMessageBox.information(self, "Cleanup Preview", "All storage areas are within policy. Nothing to clean!")
            return

        lines = [f"Found {len(plan.actions)} file(s) to remove (Total: {_format_size(plan.total_bytes)}):\n"]
        for a in plan.actions[:10]:
            lines.append(f"• {a.path.name} ({_format_size(a.size_bytes)}) — {a.reason}")
        if len(plan.actions) > 10:
            lines.append(f"  …and {len(plan.actions) - 10} more")

        QMessageBox.information(self, "Cleanup Preview", "\n".join(lines))

    def _clean_now(self) -> None:
        if not self._conn:
            return
        plan = plan_cleanup(self._conn, reason="user_clean_now")
        if not plan.actions:
            QMessageBox.information(self, "Cleanup", "Storage is already clean. Nothing removed.")
            return

        summary = execute_cleanup(self._conn, plan)
        self._refresh_all()
        QMessageBox.information(
            self, "Cleanup Complete",
            f"Removed {summary.files_deleted} file(s), freed {_format_size(summary.bytes_freed)}."
        )

    def _clear_regenerable(self) -> None:
        reply = QMessageBox.warning(
            self, "Clear Regenerable Data",
            "This will delete all temporary download caches, unpinned Drive caches, "
            "and thumbnail caches.\n\n"
            "Your database, books, custom covers, and backups will NOT be deleted.\n\n"
            "Proceed?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        freed = 0
        for key in ["drive_downloads", "partial_downloads", "deep_index_tmp"]:
            area = self._areas.get(key)
            if area and area.root.exists():
                for p in area.root.glob("*"):
                    if p.is_file():
                        try:
                            sz = p.stat().st_size
                            p.unlink()
                            freed += sz
                        except OSError:
                            pass

        self._refresh_all()
        QMessageBox.information(self, "Cleared", f"Cleared regenerable data (freed {_format_size(freed)}).")
