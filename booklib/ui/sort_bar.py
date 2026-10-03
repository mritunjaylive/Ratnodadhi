"""
sort_bar.py – toolbar widget for choosing sort field and direction.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

SORT_FIELDS = [
    ("Title",       "title"),
    ("Author",      "author"),
    ("Year",        "year"),
    ("Size",        "size_bytes"),
    ("Format",      "format"),
    ("Pages",       "pages"),
    ("Date added",  "date_added"),
]

_STYLE = """
QComboBox {
    padding: 4px 10px;
    font-size: 12px;
    min-width: 120px;
}
QPushButton {
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
    min-width: 28px;
}
"""


class SortBar(QWidget):
    """Emits sort_changed(field, ascending) when the user changes sorting."""

    sort_changed = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(_STYLE)
        self._ascending = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        from PySide6.QtWidgets import QLabel
        lbl = QLabel("Sort by:")
        lbl.setStyleSheet("color: palette(window-text); font-weight: 600; font-size: 12px; margin-right: 2px;")
        layout.addWidget(lbl)

        self._combo = QComboBox()
        for label, _ in SORT_FIELDS:
            self._combo.addItem(label)
        self._combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self._combo)

        self._dir_btn = QPushButton("↑")
        self._dir_btn.setCheckable(True)
        self._dir_btn.setChecked(True)  # ascending
        self._dir_btn.setToolTip("Toggle sort direction")
        self._dir_btn.clicked.connect(self._toggle_dir)
        layout.addWidget(self._dir_btn)
        layout.addStretch()

    def set_sort(self, field: str, ascending: bool) -> None:
        """Restore sort state from settings without emitting a signal."""
        for i, (_, f) in enumerate(SORT_FIELDS):
            if f == field:
                self._combo.blockSignals(True)
                self._combo.setCurrentIndex(i)
                self._combo.blockSignals(False)
                break
        self._ascending = ascending
        self._dir_btn.blockSignals(True)
        self._dir_btn.setChecked(ascending)
        self._dir_btn.setText("↑" if ascending else "↓")
        self._dir_btn.blockSignals(False)

    def current_field(self) -> str:
        return SORT_FIELDS[self._combo.currentIndex()][1]

    def is_ascending(self) -> bool:
        return self._ascending

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _emit(self) -> None:
        self.sort_changed.emit(self.current_field(), self._ascending)

    def _toggle_dir(self) -> None:
        self._ascending = self._dir_btn.isChecked()
        self._dir_btn.setText("↑" if self._ascending else "↓")
        self._emit()
