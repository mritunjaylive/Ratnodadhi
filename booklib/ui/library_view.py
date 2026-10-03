"""
library_view.py – grid view (QListView + delegate) and list view (QTableView).
v2: palette-aware colors, status badges, star rating display.
"""
from __future__ import annotations

import math

import json
from PySide6.QtCore import QMimeData, QModelIndex, QPointF, QSize, Qt
from PySide6.QtGui import (
    QBrush, QColor, QDrag, QFont, QFontMetrics, QPainter, QPalette, QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QListView, QStyledItemDelegate,
    QStyle, QTableView, QHeaderView,
)

from booklib.ui.library_model import (
    THUMBNAIL_SIZE, ROLE_STATUS, ROLE_MISSING, ROLE_PROGRESS, ROLE_BOOK_ID,
    ROLE_SOURCE_BADGE, ROLE_PATH,
)

ITEM_W = 150
ITEM_H = 245
PADDING = 8
TITLE_LINES = 2


def _star_polygon(cx: float, cy: float, outer: float, inner: float) -> QPolygonF:
    pts = []
    for k in range(10):
        angle = math.radians(-90 + k * 36)
        r = outer if k % 2 == 0 else inner
        pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return QPolygonF(pts)


class BookDelegate(QStyledItemDelegate):
    """Paints cover, progress bar, title, author, status badge for grid cells with modern card styling."""

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        palette: QPalette = option.palette
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover    = bool(option.state & QStyle.State_MouseOver)
        rect = option.rect

        # ── Modern Rounded Card Surface ───────────────────────────────────────
        card_rect = rect.adjusted(3, 3, -3, -3)
        if is_selected:
            # High-contrast crisp border and elevated surface without blue fill
            is_dark_theme = palette.color(QPalette.Window).lightness() < 128
            sel_border = QColor("#f3f4f6") if is_dark_theme else QColor("#0f172a")
            sel_bg = QColor(255, 255, 255, 24) if is_dark_theme else QColor(15, 23, 42, 16)
            painter.setPen(QPen(sel_border, 2.0))
            painter.setBrush(QBrush(sel_bg))
            painter.drawRoundedRect(card_rect, 8, 8)
        elif is_hover:
            hover_border = palette.color(QPalette.Mid)
            hover_bg = palette.color(QPalette.AlternateBase)
            painter.setPen(QPen(hover_border, 1.0))
            painter.setBrush(QBrush(hover_bg))
            painter.drawRoundedRect(card_rect, 8, 8)

        # ── Cover ─────────────────────────────────────────────────────────────
        pixmap = index.data(Qt.DecorationRole)
        cover_top = rect.top() + PADDING + 2
        cover_w = ITEM_W - 2 * PADDING
        cover_h = THUMBNAIL_SIZE.height()

        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(cover_w, cover_h,
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            px_x = rect.left() + (ITEM_W - scaled.width()) // 2
            # Subtle drop shadow behind cover
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 45))
            painter.drawRoundedRect(px_x + 1, cover_top + 2, scaled.width(), scaled.height(), 4, 4)
            painter.drawPixmap(px_x, cover_top, scaled)
        else:
            painter.setPen(QPen(palette.color(QPalette.Mid), 1))
            painter.setBrush(palette.color(QPalette.AlternateBase))
            painter.drawRoundedRect(rect.left() + PADDING, cover_top, cover_w, cover_h, 4, 4)

        # ── Progress bar on cover bottom edge ─────────────────────────────────
        prog_info = index.data(ROLE_PROGRESS)
        if prog_info:
            p_page, p_pct, p_total = prog_info
            fraction = 0.0
            if p_page and p_total and p_total > 0:
                fraction = min(1.0, max(0.0, p_page / p_total))
            elif p_pct:
                fraction = min(1.0, max(0.0, p_pct / 100.0))

            if fraction > 0.0:
                bar_h = 4
                bar_y = cover_top + cover_h - bar_h - 2
                bar_x = rect.left() + PADDING + 4
                bar_w = cover_w - 8
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 160))
                painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 2, 2)
                progress_color = QColor("#10b981")  # Emerald green for reading progress
                fill_w = max(4, int(bar_w * fraction))
                painter.setBrush(progress_color)
                painter.drawRoundedRect(bar_x, bar_y, fill_w, bar_h, 2, 2)

        # ── Status badge (pill badge) ─────────────────────────────────────────
        status = index.data(ROLE_STATUS)
        if status:
            from booklib.ui.theme import badge_color
            badge_c = badge_color(status)
            badge_x = rect.left() + PADDING + 5
            badge_y = cover_top + cover_h - 22
            badge_label = {"want": "Want", "reading": "Reading", "read": "Read"}.get(status, "")
            f = QFont(option.font)
            f.setPointSize(7)
            f.setBold(True)
            f.setStyleStrategy(QFont.PreferAntialias)
            fm_badge = QFontMetrics(f)
            bw = fm_badge.horizontalAdvance(badge_label) + 12
            painter.setPen(Qt.NoPen)
            painter.setBrush(badge_c)
            painter.drawRoundedRect(badge_x, badge_y, bw, 16, 8, 8)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(f)
            painter.drawText(badge_x, badge_y, bw, 16, Qt.AlignCenter, badge_label)

        # ── Cloud Source badge (pill badge, top-right of cover) ───────────────
        source_badge = index.data(ROLE_SOURCE_BADGE)
        if source_badge:
            f_src = QFont(option.font)
            f_src.setPointSize(7)
            f_src.setBold(True)
            f_src.setStyleStrategy(QFont.PreferAntialias)
            fm_src = QFontMetrics(f_src)
            bw = fm_src.horizontalAdvance(str(source_badge)) + 10
            badge_x = rect.left() + ITEM_W - PADDING - bw - 4
            badge_y = cover_top + 4
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(15, 20, 30, 200))
            painter.drawRoundedRect(badge_x, badge_y, bw, 16, 8, 8)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(f_src)
            painter.drawText(badge_x, badge_y, bw, 16, Qt.AlignCenter, str(source_badge))

        # ── Title ─────────────────────────────────────────────────────────────
        text_top = cover_top + cover_h + 8
        text_w   = ITEM_W - 2 * PADDING
        text_left = rect.left() + PADDING

        title_font = QFont(option.font)
        title_font.setPointSize(9)
        title_font.setWeight(QFont.DemiBold)
        title_font.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(title_font)
        painter.setPen(palette.color(QPalette.WindowText if not is_selected else QPalette.HighlightedText))

        title = index.data(Qt.DisplayRole) or ""
        fm = QFontMetrics(title_font)
        for line in _wrap_text(fm, title, text_w, TITLE_LINES):
            painter.drawText(text_left, text_top, text_w, fm.height(),
                             Qt.AlignLeft | Qt.AlignTop, line)
            text_top += fm.height()

        # ── Author ────────────────────────────────────────────────────────────
        from booklib.ui.library_model import ROLE_AUTHOR
        author = index.data(ROLE_AUTHOR) or ""
        af = QFont(option.font)
        af.setPointSize(8)
        af.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(af)
        disabled_text = palette.color(QPalette.PlaceholderText)
        painter.setPen(disabled_text)
        fm2 = QFontMetrics(af)
        painter.drawText(text_left, text_top + 2, text_w, fm2.height(),
                         Qt.AlignLeft | Qt.AlignTop,
                         fm2.elidedText(author, Qt.ElideRight, text_w))

        # ── Missing indicator ─────────────────────────────────────────────────
        if index.data(ROLE_MISSING):
            painter.setPen(QColor("#ef4444"))
            painter.setFont(af)
            painter.drawText(text_left, rect.bottom() - 14, text_w, 12,
                             Qt.AlignLeft, "[Missing]")

        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(ITEM_W, ITEM_H)


def _wrap_text(fm: QFontMetrics, text: str, width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip() if current else word
        if fm.horizontalAdvance(test) <= width:
            current = test
        else:
            if current:
                lines.append(fm.elidedText(current, Qt.ElideRight, width))
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(fm.elidedText(current, Qt.ElideRight, width))
    return lines[:max_lines]


class LibraryView(QListView):
    """Grid view: QListView in IconMode with BookDelegate and DND support."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setItemDelegate(BookDelegate(self))
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setModelColumn(0)

    def set_thumb_size(self, size: int) -> None:
        self.setIconSize(QSize(size, int(size * 1.4)))
        self.setGridSize(QSize(size + 30, size + 60))

    def startDrag(self, supportedActions) -> None:
        indexes = self.selectedIndexes()
        rows = {idx.row() for idx in indexes}
        model = self.model()
        if not model:
            return
        ids = [model.data(model.index(r, 0), ROLE_BOOK_ID) for r in rows]
        valid_ids = [i for i in ids if i is not None]
        if not valid_ids:
            return
        mime = QMimeData()
        mime.setData("application/x-booklib-ids", json.dumps(valid_ids).encode("utf-8"))
        from PySide6.QtCore import QUrl
        from pathlib import Path
        paths = [model.data(model.index(r, 0), ROLE_PATH) for r in rows]
        urls = [QUrl.fromLocalFile(p) for p in paths if p and Path(p).exists()]
        if urls:
            mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class LibraryTableView(QTableView):
    """List (table) view that shares the same model as LibraryView with DND support."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.setShowGrid(False)

    def startDrag(self, supportedActions) -> None:
        indexes = self.selectedIndexes()
        rows = {idx.row() for idx in indexes}
        model = self.model()
        if not model:
            return
        ids = [model.data(model.index(r, 0), ROLE_BOOK_ID) for r in rows]
        valid_ids = [i for i in ids if i is not None]
        if not valid_ids:
            return
        mime = QMimeData()
        mime.setData("application/x-booklib-ids", json.dumps(valid_ids).encode("utf-8"))
        from PySide6.QtCore import QUrl
        from pathlib import Path
        paths = [model.data(model.index(r, 0), ROLE_PATH) for r in rows]
        urls = [QUrl.fromLocalFile(p) for p in paths if p and Path(p).exists()]
        if urls:
            mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

