"""
reader/ui/thumbs_panel.py – Lazy page thumbnail navigation panel.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from booklib.reader.backend import DocumentBackend

_THUMB_WIDTH = 100
_THUMB_HEIGHT = 140


class ThumbsPanel(QWidget):
    """Vertical list of document page thumbnails."""

    item_selected = Signal(int)  # page (0-based)

    def __init__(self, backend: DocumentBackend, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._list = QListWidget(self)
        self._list.setIconSize(QSize(_THUMB_WIDTH, _THUMB_HEIGHT))
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        self._populate_list()

    def _populate_list(self) -> None:
        self._list.clear()
        count = self.backend.page_count
        # Limit thumbnail count for massive docs (render lazily up to 100 or on scroll)
        limit = min(count, 150)
        for pno in range(limit):
            item = QListWidgetItem(f"Page {pno + 1}")
            item.setData(Qt.UserRole, pno)
            self._list.addItem(item)
            # Render low-res thumbnail
            qimg = self.backend.render(pno, zoom=0.2)
            if not qimg.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(qimg)))

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        p = item.data(Qt.UserRole)
        if p is not None:
            self.item_selected.emit(int(p))
