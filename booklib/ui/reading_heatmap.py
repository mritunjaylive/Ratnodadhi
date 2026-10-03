"""
ui/reading_heatmap.py – 52-week Reading Heatmap widget drawn with QPainter.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QHelpEvent, QPainter
from PySide6.QtWidgets import QToolTip, QWidget

from booklib.stats.queries import HeatmapDay, reading_heatmap

LEVEL_COLORS_LIGHT = [
    QColor("#ebedf0"),
    QColor("#9be9a8"),
    QColor("#40c463"),
    QColor("#30a14e"),
    QColor("#216e39"),
]

LEVEL_COLORS_DARK = [
    QColor(255, 255, 255, 25),
    QColor("#0e4429"),
    QColor("#006d32"),
    QColor("#26a641"),
    QColor("#39d353"),
]


class ReadingHeatmapWidget(QWidget):
    """
    GitHub-style 52-week contribution heatmap for reading activity.
    52 columns x 7 rows representing days of the year.
    """

    CELL_SIZE = 12
    CELL_GAP = 3
    RADIUS = 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._days: list[HeatmapDay] = []
        self._cell_rects: list[tuple[QRectF, HeatmapDay]] = []
        self.setFixedHeight(self.CELL_SIZE * 7 + self.CELL_GAP * 6 + 30)
        self.setMinimumWidth(self.CELL_SIZE * 53 + self.CELL_GAP * 52 + 40)
        self.setMouseTracking(True)

    def set_data(self, days: list[HeatmapDay]) -> None:
        self._days = days
        self._recompute_layout()
        self.update()

    def load_from_db(self, conn: sqlite3.Connection) -> None:
        days = reading_heatmap(conn, total_days=364)
        self.set_data(days)

    def _recompute_layout(self) -> None:
        self._cell_rects.clear()
        if not self._days:
            return

        x_start = 30.0
        y_start = 18.0

        for idx, day in enumerate(self._days):
            col = idx // 7
            row = idx % 7
            x = x_start + col * (self.CELL_SIZE + self.CELL_GAP)
            y = y_start + row * (self.CELL_SIZE + self.CELL_GAP)
            rect = QRectF(x, y, self.CELL_SIZE, self.CELL_SIZE)
            self._cell_rects.append((rect, day))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        is_dark = self.palette().window().color().lightness() < 128
        palette_colors = LEVEL_COLORS_DARK if is_dark else LEVEL_COLORS_LIGHT
        text_color = QColor(180, 180, 180) if is_dark else QColor(100, 100, 100)

        # Day labels (Mon, Wed, Fri)
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(text_color)

        day_labels = [("Mon", 0), ("Wed", 2), ("Fri", 4)]
        y_start = 18.0
        for label, row_idx in day_labels:
            y = y_start + row_idx * (self.CELL_SIZE + self.CELL_GAP) + self.CELL_SIZE - 2
            painter.drawText(4, int(y), label)

        # Draw cells
        painter.setPen(Qt.NoPen)
        for rect, day in self._cell_rects:
            color = palette_colors[min(day.level, len(palette_colors) - 1)]
            painter.setBrush(color)
            painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        # Draw Legend in bottom right
        legend_x = self.width() - 160
        legend_y = self.height() - 10
        painter.drawText(legend_x - 35, legend_y - 2, "Less")
        for i, col in enumerate(palette_colors):
            painter.setBrush(col)
            r = QRectF(legend_x + i * (self.CELL_SIZE + 2), legend_y - self.CELL_SIZE, self.CELL_SIZE, self.CELL_SIZE)
            painter.drawRoundedRect(r, self.RADIUS, self.RADIUS)
        painter.drawText(legend_x + len(palette_colors) * (self.CELL_SIZE + 2) + 4, legend_y - 2, "More")

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        for rect, day in self._cell_rects:
            if rect.contains(pos):
                mins = day.duration_seconds // 60
                text = f"{day.date_str}: {mins} min read" if mins > 0 else f"{day.date_str}: No reading activity"
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()
        super().mouseMoveEvent(event)
