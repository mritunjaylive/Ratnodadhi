"""
star_rating.py – clickable 5-star rating widget.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QWidget

STAR_SIZE = 18
STAR_COUNT = 5


class StarRating(QWidget):
    """Emits ratingChanged(int | None); click current star to clear."""

    ratingChanged = Signal(object)  # int | None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rating: int | None = None
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(STAR_SIZE + 4)

    def rating(self) -> int | None:
        return self._rating

    def set_rating(self, rating: int | None, emit: bool = False) -> None:
        self._rating = rating
        self.update()
        if emit:
            self.ratingChanged.emit(rating)

    def sizeHint(self) -> QSize:
        return QSize(STAR_COUNT * (STAR_SIZE + 2), STAR_SIZE + 4)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        displayed = self._hover if self._hover is not None else self._rating

        for i in range(STAR_COUNT):
            x = i * (STAR_SIZE + 2) + 1
            y = 2
            filled = displayed is not None and i < displayed
            self._draw_star(painter, x, y, filled)

        painter.end()

    def _draw_star(self, painter: QPainter, x: int, y: int, filled: bool) -> None:
        import math
        palette = self.palette()
        if filled:
            color = QColor("#f59e0b")   # amber – looks good on both themes
        else:
            color = palette.color(QPalette.Disabled, QPalette.WindowText)
            color.setAlpha(90)

        painter.setPen(Qt.NoPen)
        painter.setBrush(color)

        # 5-pointed star polygon
        cx, cy = x + STAR_SIZE / 2, y + STAR_SIZE / 2
        outer, inner = STAR_SIZE / 2, STAR_SIZE / 5
        from PySide6.QtGui import QPolygonF
        from PySide6.QtCore import QPointF
        pts = []
        for k in range(10):
            angle = math.radians(-90 + k * 36)
            r = outer if k % 2 == 0 else inner
            pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
        painter.drawPolygon(QPolygonF(pts))

    def mouseMoveEvent(self, event) -> None:
        self._hover = self._star_at(event.position().x())
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            star = self._star_at(event.position().x())
            new = None if star == self._rating else star
            self.set_rating(new, emit=True)

    def _star_at(self, x: float) -> int:
        star = int(x // (STAR_SIZE + 2)) + 1
        return max(1, min(STAR_COUNT, star))
