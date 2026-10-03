"""
reader/layout.py – Layout settings, themes, and configuration for built-in reader.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QSettings

ViewMode = Literal["continuous", "single", "facing"]
ScrollMode = Literal["scrolled", "paginated"]
ThemeMode = Literal["light", "sepia", "dark", "black"]
MarginMode = Literal["narrow", "medium", "wide"]

_SETTINGS_PREFIX = "reader/"


@dataclass
class LayoutSettings:
    """Reader display and typography settings."""
    view_mode: ViewMode = "continuous"
    scroll_mode: ScrollMode = "scrolled"
    theme: ThemeMode = "light"
    font_size: float = 14.0
    margin_mode: MarginMode = "medium"
    zoom: float = 1.0
    fit_mode: str = "width"  # 'width' | 'page' | 'custom'

    def layout_key(self, width: int, height: int) -> str:
        """Unique key identifying layout for reflow caching."""
        return f"{self.font_size:.1f}|{width}|{height}|{self.margin_mode}|{self.theme}"

    def margin_pixels(self, viewport_width: int) -> int:
        """Margin in pixels based on viewport width."""
        if self.margin_mode == "narrow":
            return max(16, int(viewport_width * 0.05))
        elif self.margin_mode == "wide":
            return max(48, int(viewport_width * 0.20))
        else:  # medium
            return max(32, int(viewport_width * 0.10))

    def save_global(self) -> None:
        """Save settings globally to QSettings."""
        s = QSettings()
        s.setValue(_SETTINGS_PREFIX + "view_mode", self.view_mode)
        s.setValue(_SETTINGS_PREFIX + "scroll_mode", self.scroll_mode)
        s.setValue(_SETTINGS_PREFIX + "theme", self.theme)
        s.setValue(_SETTINGS_PREFIX + "font_size", self.font_size)
        s.setValue(_SETTINGS_PREFIX + "margin_mode", self.margin_mode)
        s.setValue(_SETTINGS_PREFIX + "fit_mode", self.fit_mode)

    @classmethod
    def load_global(cls) -> LayoutSettings:
        """Load global settings from QSettings."""
        s = QSettings()
        vm = s.value(_SETTINGS_PREFIX + "view_mode", "continuous")
        sm = s.value(_SETTINGS_PREFIX + "scroll_mode", "scrolled")
        thm = s.value(_SETTINGS_PREFIX + "theme", "light")
        fs = float(s.value(_SETTINGS_PREFIX + "font_size", 14.0))
        mm = s.value(_SETTINGS_PREFIX + "margin_mode", "medium")
        fm = s.value(_SETTINGS_PREFIX + "fit_mode", "width")
        return cls(
            view_mode=vm,
            scroll_mode=sm,
            theme=thm,
            font_size=fs,
            margin_mode=mm,
            fit_mode=fm,
        )
