"""
ui/command_palette.py – Quick searchable command palette dialog (Ctrl+K).
"""
from __future__ import annotations

import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QHBoxLayout,
    QWidget,
)

from booklib.actions import get_all_defs, ActionDef

logger = logging.getLogger(__name__)

# In-memory MRU action IDs
_MRU_ACTION_IDS: list[str] = []


class CommandPalette(QDialog):
    """Searchable command launcher modal."""

    action_triggered = Signal(str)  # action_id

    def __init__(self, main_window, parent=None) -> None:
        super().__init__(parent or main_window, Qt.Popup | Qt.FramelessWindowHint)
        self._window = main_window
        self.resize(520, 360)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._setup_ui()
        self._populate_list("")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Search line
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Type a command or shortcut…")
        self._search_edit.setStyleSheet(
            "padding: 8px 12px; font-size: 14px; border: 1px solid palette(mid); border-radius: 6px;"
        )
        self._search_edit.textChanged.connect(self._populate_list)
        self._search_edit.returnPressed.connect(self._execute_selected)
        layout.addWidget(self._search_edit)

        # Results list
        self._list_widget = QListWidget()
        self._list_widget.setStyleSheet(
            "QListWidget::item { padding: 6px 10px; border-radius: 4px; }"
            "QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }"
        )
        self._list_widget.itemDoubleClicked.connect(lambda _: self._execute_selected())
        layout.addWidget(self._list_widget)

    def _populate_list(self, query: str) -> None:
        self._list_widget.clear()
        q = query.strip().lower()

        defs = get_all_defs()

        # Sort so MRU items appear higher when query is empty
        if not q and _MRU_ACTION_IDS:
            mru_set = {aid: idx for idx, aid in enumerate(_MRU_ACTION_IDS)}
            defs.sort(key=lambda d: mru_set.get(d.id, 999))

        for d in defs:
            searchable = f"{d.menu} {d.text} {d.default_shortcut} {d.id}".lower()
            if q and q not in searchable:
                continue

            item = QListWidgetItem()
            item.setData(Qt.UserRole, d.id)

            # Custom row widget with label on left and shortcut on right
            widget = QWidget()
            h_layout = QHBoxLayout(widget)
            h_layout.setContentsMargins(4, 2, 4, 2)

            label_text = f"<b>{d.menu}:</b> {d.text}" if d.menu else d.text
            lbl = QLabel(label_text)
            h_layout.addWidget(lbl)

            h_layout.addStretch()
            if d.default_shortcut:
                sc_lbl = QLabel(d.default_shortcut)
                sc_lbl.setStyleSheet(
                    "background: palette(midlight); color: palette(text); padding: 2px 6px; "
                    "border-radius: 3px; font-size: 11px; font-family: monospace;"
                )
                h_layout.addWidget(sc_lbl)

            item.setSizeHint(widget.sizeHint())
            self._list_widget.addItem(item)
            self._list_widget.setItemWidget(item, widget)

        if self._list_widget.count() > 0:
            self._list_widget.setCurrentRow(0)

    def _execute_selected(self) -> None:
        item = self._list_widget.currentItem()
        if not item:
            return
        action_id = item.data(Qt.UserRole)
        if not action_id:
            return

        # Update MRU
        if action_id in _MRU_ACTION_IDS:
            _MRU_ACTION_IDS.remove(action_id)
        _MRU_ACTION_IDS.insert(0, action_id)

        self.accept()
        self.action_triggered.emit(action_id)
