"""
drive_connect_dialog.py – Connect Google Drive account dialog.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QWidget,
    QProgressBar,
    QTabWidget,
    QFormLayout,
)

from booklib.config import GOOGLE_CLIENT_FILE
from booklib.drive.auth import (
    import_credentials_file,
    import_credentials_raw,
    run_oauth_flow,
    TokenStore,
)
from booklib.db.repository import Repository
from booklib.ui.theme import apply_window_rounding

logger = logging.getLogger(__name__)


class OAuthWorker(QThread):
    finished_success = Signal(str, str)  # email, display_name
    finished_error = Signal(str)

    def __init__(self, token_store: TokenStore):
        super().__init__()
        self._token_store = token_store

    def run(self) -> None:
        try:
            email, refresh_token, display_name = run_oauth_flow(token_store=self._token_store)
            self.finished_success.emit(email, display_name or "")
        except Exception as exc:
            logger.exception("OAuth flow failed")
            self.finished_error.emit(str(exc))


class DriveConnectDialog(QDialog):
    """Dialog to configure Google credentials and sign in."""

    account_connected = Signal(str)  # email

    def __init__(self, repo: Repository, token_store: TokenStore | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Connect Google Drive")
        self.setFixedWidth(540)
        self.setModal(True)
        apply_window_rounding(self)

        self._repo = repo
        self._token_store = token_store or TokenStore()
        self._oauth_worker: OAuthWorker | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header info
        info_label = QLabel(
            "<h3 style='margin-bottom: 4px;'>Sign in with Google Drive</h3>"
            "<p style='color: palette(window-text); line-height: 1.4;'>"
            "To link Google Drive, provide an OAuth 2.0 Client from your Google Cloud Console.<br>"
            "<small style='color: #64748b;'>"
            "1. Enable the <b>Google Drive API</b> in Google Cloud.<br>"
            "2. Create an OAuth 2.0 Client ID for a <b>Desktop app</b>.<br>"
            "3. Select the downloaded JSON file or paste the Client ID & Secret below."
            "</small></p>"
        )
        info_label.setWordWrap(True)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info_label)

        # Credentials Tabs: File vs Direct Input
        self._tabs = QTabWidget()

        # Tab 1: File import
        tab_file = QWidget()
        file_layout = QVBoxLayout(tab_file)
        file_layout.setContentsMargins(10, 14, 10, 10)
        file_layout.setSpacing(8)

        file_box = QHBoxLayout()
        self._path_edit = QLineEdit()
        if GOOGLE_CLIENT_FILE.exists():
            self._path_edit.setText(str(GOOGLE_CLIENT_FILE))
        self._path_edit.setPlaceholderText("Path to client_secret.json")
        file_box.addWidget(self._path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_credentials)
        file_box.addWidget(browse_btn)
        file_layout.addLayout(file_box)

        self._file_status_label = QLabel()
        if GOOGLE_CLIENT_FILE.exists():
            self._file_status_label.setText("✓ Existing credentials file found.")
            self._file_status_label.setStyleSheet("color: #10b981; font-size: 11px;")
        else:
            self._file_status_label.setText("Select your client_secret_*.json file.")
            self._file_status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        file_layout.addWidget(self._file_status_label)

        self._tabs.addTab(tab_file, "Credentials File (.json)")

        # Tab 2: Manual Client ID & Secret
        tab_manual = QWidget()
        manual_layout = QFormLayout(tab_manual)
        manual_layout.setContentsMargins(10, 14, 10, 10)
        manual_layout.setSpacing(10)

        self._client_id_edit = QLineEdit()
        self._client_id_edit.setPlaceholderText("e.g. 123456789-xxx.apps.googleusercontent.com")
        self._client_secret_edit = QLineEdit()
        self._client_secret_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self._client_secret_edit.setPlaceholderText("e.g. GOCSPX-xxxxxxxxx")

        manual_layout.addRow("Client ID:", self._client_id_edit)
        manual_layout.addRow("Client Secret:", self._client_secret_edit)
        self._tabs.addTab(tab_manual, "Client ID & Secret")

        layout.addWidget(self._tabs)

        # Progress indicator
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("font-size: 12px; font-weight: 500;")
        layout.addWidget(self._status_label)

        # Action buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self._cancel_btn)

        self._signin_btn = QPushButton("Sign in with Google...")
        self._signin_btn.setDefault(True)
        self._signin_btn.clicked.connect(self._start_signin)
        btn_box.addWidget(self._signin_btn)

        layout.addLayout(btn_box)

    def _browse_credentials(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Google Client Secrets JSON", "", "JSON Files (*.json)"
        )
        if path:
            self._path_edit.setText(path)
            self._file_status_label.setText("Selected file: " + Path(path).name)
            self._file_status_label.setStyleSheet("color: palette(window-text); font-size: 11px;")

    def _start_signin(self) -> None:
        current_tab = self._tabs.currentIndex()
        if current_tab == 0:
            # File import mode
            raw_path = self._path_edit.text().strip()
            if not raw_path or not Path(raw_path).exists():
                QMessageBox.warning(
                    self, "Missing Credentials",
                    "Please browse and select a valid client_secret.json file,\n"
                    "or switch to the 'Client ID & Secret' tab to enter them directly."
                )
                return

            client_file = Path(raw_path)
            try:
                import_credentials_file(client_file)
            except Exception as exc:
                QMessageBox.critical(self, "Invalid File", f"Error reading secrets file:\n{exc}")
                return
        else:
            # Direct text input mode
            cid = self._client_id_edit.text().strip()
            csec = self._client_secret_edit.text().strip()
            if not cid or not csec:
                QMessageBox.warning(
                    self, "Missing Fields",
                    "Please enter both Client ID and Client Secret."
                )
                return
            try:
                import_credentials_raw(cid, csec)
            except Exception as exc:
                QMessageBox.critical(self, "Invalid Input", f"Error saving credentials:\n{exc}")
                return

        self._signin_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._status_label.setStyleSheet("color: #d97706; font-size: 12px; font-weight: 500;")
        self._status_label.setText(
            "Opening browser for Google authorization...\n"
            "Please complete the Google sign-in prompt."
        )

        self._oauth_worker = OAuthWorker(self._token_store)
        self._oauth_worker.finished_success.connect(self._on_oauth_success)
        self._oauth_worker.finished_error.connect(self._on_oauth_error)
        self._oauth_worker.start()

    def _on_oauth_success(self, email: str, display_name: str) -> None:
        self._progress_bar.setVisible(False)
        self._signin_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)

        # Upsert account in DB
        self._repo.upsert_drive_account(
            email=email,
            display_name=display_name,
            provider="gdrive",
        )

        self._status_label.setStyleSheet("color: #10b981; font-size: 12px; font-weight: 600;")
        self._status_label.setText(f"Connected: {email}")

        QMessageBox.information(
            self, "Google Drive Connected",
            f"Successfully connected Google Drive account:\n{email}\n\n"
            f"You can now add Google Drive folders to your library."
        )
        self.account_connected.emit(email)
        self.accept()

    def _on_oauth_error(self, err_msg: str) -> None:
        self._progress_bar.setVisible(False)
        self._signin_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._status_label.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 500;")
        self._status_label.setText(f"Sign-in failed: {err_msg}")
        QMessageBox.critical(
            self, "Sign-in Error",
            f"Failed to authenticate with Google Drive:\n{err_msg}"
        )
