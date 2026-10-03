"""
reader/ui/selection_popup.py – Floating selection toolbar for quick highlight, note, or copy.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QStyle,
    QToolButton,
    QWidget,
)


def _color_icon(color_hex: str) -> QIcon:
    pix = QPixmap(16, 16)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color_hex))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 14, 14)
    p.end()
    return QIcon(pix)


class SelectionPopup(QWidget):
    """Floating toolbar appearing near selected text."""

    highlight_requested = Signal(str)  # color_name
    note_requested = Signal()
    copy_requested = Signal()

    COLORS = [
        ("yellow", "#FFEB3B"),
        ("green", "#4CAF50"),
        ("blue", "#2196F3"),
        ("pink", "#E91E63"),
        ("orange", "#FF9800"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet("""
            QWidget {
                background: #2b2b2b;
                border-radius: 6px;
                padding: 2px;
            }
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px;
                color: white;
            }
            QToolButton:hover {
                background: #3e3e3e;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        for name, hex_code in self.COLORS:
            btn = QToolButton(self)
            btn.setIcon(_color_icon(hex_code))
            btn.setToolTip(f"Highlight {name.capitalize()} (H)")
            btn.clicked.connect(lambda _, n=name: self._on_highlight(n))
            layout.addWidget(btn)

        btn_note = QToolButton(self)
        btn_note.setIcon(self.style().standardIcon(QStyle.SP_FileDialogInfoView))
        btn_note.setText("Note")
        btn_note.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_note.setToolTip("Add Note (N)")
        btn_note.clicked.connect(self._on_note)
        layout.addWidget(btn_note)

        btn_copy = QToolButton(self)
        btn_copy.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        btn_copy.setText("Copy")
        btn_copy.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_copy.setToolTip("Copy Text")
        btn_copy.clicked.connect(self._on_copy)
        layout.addWidget(btn_copy)

    def _on_highlight(self, color: str) -> None:
        self.hide()
        self.highlight_requested.emit(color)

    def _on_note(self) -> None:
        self.hide()
        self.note_requested.emit()

    def _on_copy(self) -> None:
        self.hide()
        self.copy_requested.emit()
