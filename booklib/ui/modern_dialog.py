"""
modern_dialog.py – Base dialog with circular/rounded corners, sleek custom title bar,
smooth dragging, and theme-aware styling.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QIcon, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from booklib.app import get_app_icon
from booklib.ui.theme import apply_window_rounding


class ModernDialog(QDialog):
    """
    A modern dialog with circular/rounded corners, integrated draggable title bar,
    translucent window background, and sleek theme-aware styling.
    """

    def __init__(self, parent: QWidget | None = None, title: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        apply_window_rounding(self)

        self._drag_pos: QPoint | None = None

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(10, 10, 10, 10)

        self._container = QFrame(self)
        self._container.setObjectName("modernDialogContainer")
        self._container.setStyleSheet("""
            QFrame#modernDialogContainer {
                background-color: palette(window);
                border: 1px solid palette(mid);
                border-radius: 14px;
            }
        """)
        self._root_layout.addWidget(self._container)

        self._main_layout = QVBoxLayout(self._container)
        self._main_layout.setContentsMargins(20, 16, 20, 18)
        self._main_layout.setSpacing(14)

        # Title bar
        self._title_bar = QHBoxLayout()
        self._title_bar.setContentsMargins(0, 0, 0, 4)
        self._title_bar.setSpacing(8)

        self._icon_lbl = QLabel()
        ico = get_app_icon()
        if not ico.isNull():
            self._icon_lbl.setPixmap(ico.pixmap(18, 18))
        self._title_bar.addWidget(self._icon_lbl)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: palette(window-text);")
        self._title_bar.addWidget(self._title_lbl)

        self._title_bar.addStretch()

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.setToolTip("Close")
        self._close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: palette(placeholder-text);
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton:hover {
                background: #ef4444;
                color: #ffffff;
            }
        """)
        self._close_btn.clicked.connect(self.reject)
        self._title_bar.addWidget(self._close_btn)
        self._main_layout.addLayout(self._title_bar)

        self._content_layout = QVBoxLayout()
        self._content_layout.setSpacing(12)
        self._main_layout.addLayout(self._content_layout)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def setWindowTitle(self, title: str) -> None:
        super().setWindowTitle(title)
        if hasattr(self, "_title_lbl"):
            self._title_lbl.setText(title)

    def setWindowIcon(self, icon: QIcon) -> None:
        super().setWindowIcon(icon)
        if hasattr(self, "_icon_lbl") and not icon.isNull():
            self._icon_lbl.setPixmap(icon.pixmap(18, 18))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 45:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)
