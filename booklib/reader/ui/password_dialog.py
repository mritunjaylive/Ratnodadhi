"""
reader/ui/password_dialog.py – Password prompt for encrypted documents.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class PasswordDialog(QDialog):
    """Prompts the user for document password (never stored)."""

    def __init__(self, filename: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Password Protected Document")
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)

        lbl = QLabel(f"The document <b>{filename}</b> is encrypted.<br>Please enter the password:", self)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.input = QLineEdit(self)
        self.input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_password(self) -> str:
        return self.input.text()
