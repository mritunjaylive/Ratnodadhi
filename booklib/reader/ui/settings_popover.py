"""
reader/ui/settings_popover.py – Reader layout, font size, margins, and theme dialog.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from booklib.reader.layout import LayoutSettings


class SettingsDialog(QDialog):
    """Dialog to adjust typography, margins, view mode, and theme."""

    settings_changed = Signal(object)  # LayoutSettings

    def __init__(self, current_settings: LayoutSettings, is_reflowable: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reader Display Settings")
        self.setFixedWidth(340)
        self.settings = current_settings
        self.is_reflowable = is_reflowable

        main_layout = QVBoxLayout(self)

        form = QFormLayout()

        # 1. Theme
        theme_layout = QHBoxLayout()
        self._theme_group = QButtonGroup(self)
        for th in ["light", "sepia", "dark", "black"]:
            btn = QRadioButton(th.capitalize(), self)
            btn.setChecked(self.settings.theme == th)
            self._theme_group.addButton(btn)
            theme_layout.addWidget(btn)
            btn.toggled.connect(self._on_change)
        form.addRow("Theme:", theme_layout)

        # 2. View Mode
        view_layout = QHBoxLayout()
        self._view_group = QButtonGroup(self)
        for vm in ["continuous", "single", "facing"]:
            btn = QRadioButton(vm.capitalize(), self)
            btn.setChecked(self.settings.view_mode == vm)
            self._view_group.addButton(btn)
            view_layout.addWidget(btn)
            btn.toggled.connect(self._on_change)
        form.addRow("View Mode:", view_layout)

        # 3. Reflowable typography options
        if self.is_reflowable:
            self._font_spin = QDoubleSpinBox(self)
            self._font_spin.setRange(8.0, 40.0)
            self._font_spin.setSingleStep(1.0)
            self._font_spin.setValue(self.settings.font_size)
            self._font_spin.valueChanged.connect(self._on_change)
            form.addRow("Font Size (pt):", self._font_spin)

            margin_layout = QHBoxLayout()
            self._margin_group = QButtonGroup(self)
            for mm in ["narrow", "medium", "wide"]:
                btn = QRadioButton(mm.capitalize(), self)
                btn.setChecked(self.settings.margin_mode == mm)
                self._margin_group.addButton(btn)
                margin_layout.addWidget(btn)
                btn.toggled.connect(self._on_change)
            form.addRow("Margins:", margin_layout)

        main_layout.addLayout(form)

        # Close button
        close_btn = QPushButton("Done", self)
        close_btn.clicked.connect(self.accept)
        main_layout.addWidget(close_btn)

    def _on_change(self) -> None:
        # Collect values
        for btn in self._theme_group.buttons():
            if btn.isChecked():
                self.settings.theme = btn.text().lower()

        for btn in self._view_group.buttons():
            if btn.isChecked():
                self.settings.view_mode = btn.text().lower()

        if self.is_reflowable:
            self.settings.font_size = self._font_spin.value()
            for btn in self._margin_group.buttons():
                if btn.isChecked():
                    self.settings.margin_mode = btn.text().lower()

        self.settings.save_global()
        self.settings_changed.emit(self.settings)
