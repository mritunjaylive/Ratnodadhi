"""
reader/ui/toc_panel.py – Table of contents navigation panel.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from booklib.reader.backend import TocEntry


class TocPanel(QWidget):
    """Panel showing document table of contents."""

    item_selected = Signal(int)  # target page (0-based)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

        self._empty_label = QLabel("No table of contents", self)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: gray; padding: 20px;")
        layout.addWidget(self._empty_label)

    def load_toc(self, entries: list[TocEntry]) -> None:
        """Populate tree with TocEntry hierarchy."""
        self._tree.clear()
        if not entries:
            self._tree.hide()
            self._empty_label.show()
            return

        self._empty_label.hide()
        self._tree.show()

        stack: list[tuple[int, QTreeWidgetItem]] = []

        for entry in entries:
            item = QTreeWidgetItem([f"{entry.title}  (p. {entry.page + 1})"])
            item.setData(0, Qt.UserRole, entry.page)

            # Pop deeper or equal levels
            while stack and stack[-1][0] >= entry.level:
                stack.pop()

            if stack:
                stack[-1][1].addChild(item)
            else:
                self._tree.addTopLevelItem(item)

            stack.append((entry.level, item))

        self._tree.expandAll()

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        page = item.data(0, Qt.UserRole)
        if page is not None:
            self.item_selected.emit(int(page))
