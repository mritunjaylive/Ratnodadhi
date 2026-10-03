"""
download_dialog.py – Progress dialog for downloading Google Drive books.
"""
from __future__ import annotations

import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)

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


class DownloadProgressDialog(QDialog):
    """Modal or modeless dialog showing book download progress with cancel."""

    cancelled = Signal()

    def __init__(self, book_title: str, total_bytes: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Downloading Book")
        self.setFixedWidth(420)
        self.setModal(True)
        apply_window_rounding(self)

        self._total_bytes = total_bytes
        self._is_cancelled = False

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._title_label = QLabel(f"Downloading <b>{book_title}</b>...")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._progress_bar = QProgressBar()
        if total_bytes > 0:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(0)
        else:
            self._progress_bar.setRange(0, 0)  # indeterminate
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel("Starting download...")
        layout.addWidget(self._status_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._handle_cancel)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    def _handle_cancel(self) -> None:
        self._is_cancelled = True
        self._status_label.setText("Cancelling...")
        self._cancel_btn.setEnabled(False)
        self.cancelled.emit()
        self.reject()

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def update_progress(self, downloaded: int, total: int) -> None:
        if self._is_cancelled:
            return
        if total > 0:
            self._progress_bar.setRange(0, 100)
            pct = int((downloaded / total) * 100)
            self._progress_bar.setValue(pct)
            self._status_label.setText(
                f"{_format_size(downloaded)} of {_format_size(total)} ({pct}%)"
            )
        else:
            self._progress_bar.setRange(0, 0)
            self._status_label.setText(f"{_format_size(downloaded)} downloaded")
