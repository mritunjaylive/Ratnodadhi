"""
reader/ui/page_view.py – Scrolling document canvas painting pages and overlays.

Supports:
- Modes: Continuous vertical, Single page, Facing pages.
- High-DPI rendering via devicePixelRatio.
- Interactive text selection with hit-testing.
- Visual overlays: search hits, selection, highlights, bookmark ribbon.
- Clickable internal and external links.
- Scanned / no-text page indicator.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QImage,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QMessageBox

from booklib.reader.backend import DocumentBackend, Hit, Link, Locator, TextWord
from booklib.reader.layout import LayoutSettings
from booklib.reader.render import LRUPageCache, RenderWorker
from booklib.reader.textlayer import TextLayer

logger = logging.getLogger(__name__)

# Overlay Colors
SELECTION_COLOR = QColor(64, 156, 255, 110)
HIT_COLOR = QColor(255, 235, 59, 140)
CURRENT_HIT_COLOR = QColor(255, 152, 0, 180)
RIBBON_COLOR = QColor(220, 53, 69, 220)


class PageView(QAbstractScrollArea):
    """Interactive canvas displaying pages and annotations."""

    page_changed = Signal(int)              # current visible page (0-based)
    text_selected = Signal(int, str, list)  # page, text, rects
    link_clicked = Signal(object)           # Link
    open_external_requested = Signal()

    def __init__(
        self,
        backend: DocumentBackend,
        layout_settings: LayoutSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.settings = layout_settings or LayoutSettings()
        self.text_layer = TextLayer(backend)

        # Rendering
        self._cache = LRUPageCache()
        self._worker = RenderWorker(backend, self._cache, self)
        self._worker.page_rendered.connect(self._on_page_rendered)
        self._worker.start()

        # Geometry & Navigation
        self.current_page = 0
        self._generation = 1
        self._rendered_images: dict[int, QImage] = {}

        # Selection state
        self._is_selecting = False
        self._sel_page: int = -1
        self._sel_start_word: int = -1
        self._sel_end_word: int = -1

        # Search hits & overlays
        self._search_hits: list[Hit] = []
        self._active_hit: Hit | None = None
        self._bookmarked_pages: set[int] = set()
        self._annotation_rects: dict[int, list[tuple[tuple[float, float, float, float], str]]] = {}

        # Scroll / Viewport settings
        self.setMouseTracking(True)
        self.viewport().setCursor(Qt.IBeamCursor)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.viewport().update())
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def closeEvent(self, event) -> None:
        self._worker.stop()
        super().closeEvent(event)

    # ── Configuration & Relayout ──────────────────────────────────────────────

    def update_settings(self, settings: LayoutSettings) -> None:
        """Apply new layout settings and re-render."""
        self.settings = settings
        self._generation += 1
        self._worker.set_generation(self._generation)
        self._rendered_images.clear()
        self.text_layer.clear_cache()

        if self.backend.is_reflowable:
            vp_w = max(400, self.viewport().width())
            vp_h = max(500, self.viewport().height())
            self.backend.layout(vp_w, vp_h, self.settings.font_size)

        self._update_scroll_ranges()
        self.viewport().update()

    def set_search_hits(self, hits: list[Hit], active_hit: Hit | None = None) -> None:
        self._search_hits = hits
        self._active_hit = active_hit
        self.viewport().update()

    def set_bookmarks(self, pages: set[int]) -> None:
        self._bookmarked_pages = pages
        self.viewport().update()

    def set_annotations(self, annots_by_page: dict[int, list[tuple[tuple[float, float, float, float], str]]]) -> None:
        self._annotation_rects = annots_by_page
        self.viewport().update()

    def goto_page(self, page: int, y_fraction: float = 0.0) -> None:
        """Navigate to specific page and vertical offset."""
        if self.backend.page_count == 0:
            return
        page = max(0, min(page, self.backend.page_count - 1))
        self.current_page = page

        if self.settings.view_mode == "continuous":
            total_y = 0
            for p in range(page):
                w, h = self.backend.get_page_size(p)
                total_y += int(h * self.settings.zoom) + 16
            page_w, page_h = self.backend.get_page_size(page)
            target_y = total_y + int(page_h * self.settings.zoom * y_fraction)
            self._programmatic_scroll = True
            try:
                self.verticalScrollBar().setValue(target_y)
            finally:
                self._programmatic_scroll = False
        else:
            self.verticalScrollBar().setValue(0)
            self._request_visible_pages()
            self.viewport().update()

        self.page_changed.emit(self.current_page)

    # ── Paint Event ────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)

        # Background color based on theme
        bg_color = self._theme_bg_color()
        painter.fillRect(self.viewport().rect(), bg_color)

        if self.backend.page_count == 0:
            painter.setPen(QColor(128, 128, 128))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, "No pages to display")
            return

        visible_pages = self._get_visible_pages()
        for pno, rect in visible_pages:
            self._paint_page(painter, pno, rect)

    def _theme_bg_color(self) -> QColor:
        theme = self.settings.theme
        if theme == "dark":
            return QColor(30, 30, 30)
        elif theme == "black":
            return QColor(0, 0, 0)
        elif theme == "sepia":
            return QColor(244, 236, 216)
        return QColor(240, 240, 242)

    def _paint_page(self, painter: QPainter, page: int, target_rect: QRect) -> None:
        # Page drop shadow and white/dark canvas
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 35))
        painter.drawRect(target_rect.translated(3, 3))

        page_bg = QColor(26, 26, 26) if self.settings.theme in ("dark", "black") else QColor(255, 255, 255)
        painter.setBrush(page_bg)
        painter.drawRect(target_rect)

        # Rendered image
        img = self._rendered_images.get(page)
        if img is not None and not img.isNull():
            painter.drawImage(target_rect, img)
        else:
            # Placeholder loading box
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(target_rect, Qt.AlignCenter, f"Loading page {page + 1}…")

        # Overlays: annotations, hits, selection, bookmarks
        self._paint_overlays(painter, page, target_rect)

    def _paint_overlays(self, painter: QPainter, page: int, target_rect: QRect) -> None:
        pw, ph = self.backend.get_page_size(page)
        if pw <= 0 or ph <= 0:
            return

        sx = target_rect.width() / pw
        sy = target_rect.height() / ph

        # 1. Stored Annotations
        if page in self._annotation_rects:
            for (x0, y0, x1, y1), color_name in self._annotation_rects[page]:
                rx = target_rect.left() + x0 * sx
                ry = target_rect.top() + y0 * sy
                rw = (x1 - x0) * sx
                rh = (y1 - y0) * sy
                c = self._color_from_name(color_name)
                c.setAlpha(120)
                painter.fillRect(QRectF(rx, ry, rw, rh), c)

        # 2. Search Hits
        for hit in self._search_hits:
            if hit.page == page:
                is_active = (self._active_hit is not None and self._active_hit.page == page and hit.rects == self._active_hit.rects)
                c = CURRENT_HIT_COLOR if is_active else HIT_COLOR
                painter.setBrush(c)
                painter.setPen(QPen(QColor(230, 81, 0), 1.5) if is_active else Qt.NoPen)
                for (x0, y0, x1, y1) in hit.rects:
                    rx = target_rect.left() + x0 * sx
                    ry = target_rect.top() + y0 * sy
                    rw = (x1 - x0) * sx
                    rh = (y1 - y0) * sy
                    painter.drawRect(QRectF(rx, ry, rw, rh))

        # 3. Active Text Selection
        if self._sel_page == page and self._sel_start_word >= 0 and self._sel_end_word >= 0:
            rects = self.text_layer.get_selection_rects(page, self._sel_start_word, self._sel_end_word)
            painter.setBrush(SELECTION_COLOR)
            painter.setPen(Qt.NoPen)
            for (x0, y0, x1, y1) in rects:
                rx = target_rect.left() + x0 * sx
                ry = target_rect.top() + y0 * sy
                rw = (x1 - x0) * sx
                rh = (y1 - y0) * sy
                painter.drawRect(QRectF(rx, ry, rw, rh))

        # 4. Bookmark Ribbon
        if page in self._bookmarked_pages:
            ribbon_w = 20
            ribbon_h = 32
            rx = target_rect.right() - ribbon_w - 12
            ry = target_rect.top()
            painter.setBrush(RIBBON_COLOR)
            painter.setPen(Qt.NoPen)
            painter.drawRect(rx, ry, ribbon_w, ribbon_h)

        # 5. Scanned / No text notice
        words = self.text_layer.get_words(page)
        if not words:
            painter.setPen(QColor(180, 180, 180, 160))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(
                QRect(target_rect.left() + 10, target_rect.bottom() - 25, 200, 20),
                Qt.AlignLeft,
                "No text layer on page",
            )

    def _color_from_name(self, name: str) -> QColor:
        table = {
            "yellow": QColor(255, 235, 59),
            "green": QColor(76, 175, 80),
            "blue": QColor(33, 150, 243),
            "pink": QColor(233, 30, 99),
            "orange": QColor(255, 152, 0),
        }
        return table.get(name.lower(), QColor(255, 235, 59))

    # ── Geometry and View Calculation ─────────────────────────────────────────

    def _get_visible_pages(self) -> list[tuple[int, QRect]]:
        """Return list of (page_index, viewport_target_rect) for visible pages."""
        res: list[tuple[int, QRect]] = []
        if self.backend.page_count == 0:
            return res

        vp_w = self.viewport().width()
        vp_h = self.viewport().height()

        mode = self.settings.view_mode
        if mode == "single":
            pno = self.current_page
            pw, ph = self.backend.get_page_size(pno)
            zoom = self._effective_zoom(pw, ph)
            dw, dh = int(pw * zoom), int(ph * zoom)
            x = max(16, (vp_w - dw) // 2)
            y = max(16, (vp_h - dh) // 2)
            res.append((pno, QRect(x, y, dw, dh)))

        elif mode == "facing":
            pno = self.current_page
            left_pno = pno if pno % 2 == 0 else pno - 1
            right_pno = left_pno + 1

            pw1, ph1 = self.backend.get_page_size(left_pno)
            zoom = self._effective_zoom(pw1 * 2, ph1)
            dw1, dh1 = int(pw1 * zoom), int(ph1 * zoom)

            mid_x = vp_w // 2
            y = max(16, (vp_h - dh1) // 2)
            res.append((left_pno, QRect(mid_x - dw1 - 8, y, dw1, dh1)))

            if right_pno < self.backend.page_count:
                pw2, ph2 = self.backend.get_page_size(right_pno)
                dw2, dh2 = int(pw2 * zoom), int(ph2 * zoom)
                res.append((right_pno, QRect(mid_x + 8, y, dw2, dh2)))

        else:  # continuous
            scroll_y = self.verticalScrollBar().value()
            cur_y = -scroll_y + 16
            for pno in range(self.backend.page_count):
                pw, ph = self.backend.get_page_size(pno)
                zoom = self._effective_zoom(pw, ph)
                dw, dh = int(pw * zoom), int(ph * zoom)
                x = max(16, (vp_w - dw) // 2)
                rect = QRect(x, cur_y, dw, dh)
                # Check intersection with viewport
                if cur_y + dh >= 0 and cur_y <= vp_h:
                    res.append((pno, rect))
                cur_y += dh + 16
                if cur_y > vp_h + 1000:
                    break

        return res

    def _effective_zoom(self, page_w: float, page_h: float) -> float:
        fit = self.settings.fit_mode
        vp_w = max(200, self.viewport().width() - 32)
        vp_h = max(200, self.viewport().height() - 32)

        if fit == "width" and page_w > 0:
            return vp_w / page_w
        elif fit == "page" and page_w > 0 and page_h > 0:
            return min(vp_w / page_w, vp_h / page_h)
        return self.settings.zoom

    def _update_scroll_ranges(self) -> None:
        if self.backend.page_count == 0:
            self.verticalScrollBar().setRange(0, 0)
            return

        if self.settings.view_mode == "continuous":
            total_h = 16
            max_w = 0
            for pno in range(self.backend.page_count):
                pw, ph = self.backend.get_page_size(pno)
                zoom = self._effective_zoom(pw, ph)
                total_h += int(ph * zoom) + 16
                max_w = max(max_w, int(pw * zoom))

            vp_h = self.viewport().height()
            self.verticalScrollBar().setRange(0, max(0, total_h - vp_h))
            self.verticalScrollBar().setPageStep(vp_h)
        else:
            self.verticalScrollBar().setRange(0, 0)

    def _on_scroll(self, value: int) -> None:
        # Determine current visible page in continuous mode (only if user scrolled and scroll range exists)
        if (self.settings.view_mode == "continuous"
                and not getattr(self, "_programmatic_scroll", False)
                and self.verticalScrollBar().maximum() > 0):
            y = 16
            for pno in range(self.backend.page_count):
                pw, ph = self.backend.get_page_size(pno)
                zoom = self._effective_zoom(pw, ph)
                page_h = int(ph * zoom) + 16
                if y + page_h / 2 >= value:
                    if self.current_page != pno:
                        self.current_page = pno
                        self.page_changed.emit(self.current_page)
                    break
                y += page_h

        self._request_visible_pages()
        self.viewport().update()

    def _request_visible_pages(self) -> None:
        dpr = self.devicePixelRatioF()
        invert = self.settings.theme in ("dark", "black")
        sepia = self.settings.theme == "sepia"
        lkey = self.settings.layout_key(self.viewport().width(), self.viewport().height())

        visible = self._get_visible_pages()
        for pno, _ in visible:
            pw, ph = self.backend.get_page_size(pno)
            zoom = self._effective_zoom(pw, ph)
            self._worker.request_page(
                pno,
                zoom,
                dpr=dpr,
                invert=invert,
                sepia=sepia,
                layout_key=lkey,
                generation=self._generation,
            )

        # Prefetch next and previous
        if visible:
            min_p = visible[0][0]
            max_p = visible[-1][0]
            for pref in (max_p + 1, max_p + 2, min_p - 1):
                if 0 <= pref < self.backend.page_count:
                    pw, ph = self.backend.get_page_size(pref)
                    zoom = self._effective_zoom(pw, ph)
                    self._worker.request_page(
                        pref,
                        zoom,
                        dpr=dpr,
                        invert=invert,
                        sepia=sepia,
                        layout_key=lkey,
                        generation=self._generation,
                        is_prefetch=True,
                    )

    def _on_page_rendered(self, page: int, image: QImage, gen: int) -> None:
        if gen >= self._generation:
            self._rendered_images[page] = image
            self.viewport().update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scroll_ranges()
        self._request_visible_pages()

    # ── Mouse Interaction & Text Selection ────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            hit_page, pt_page = self._viewport_to_page(pos)
            if hit_page >= 0 and pt_page is not None:
                # Check links first
                links = self.backend.links(hit_page)
                for l in links:
                    x0, y0, x1, y1 = l.rect
                    if x0 <= pt_page.x() <= x1 and y0 <= pt_page.y() <= y1:
                        self._handle_link(l)
                        return

                # Text hit-test
                w_idx = self.text_layer.hit_test(hit_page, pt_page.x(), pt_page.y())
                if w_idx is not None:
                    self._is_selecting = True
                    self._sel_page = hit_page
                    self._sel_start_word = w_idx
                    self._sel_end_word = w_idx
                    self.viewport().update()
                else:
                    self._clear_selection()
            else:
                self._clear_selection()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._is_selecting and self._sel_page >= 0:
            hit_page, pt_page = self._viewport_to_page(pos)
            if hit_page == self._sel_page and pt_page is not None:
                w_idx = self.text_layer.hit_test(hit_page, pt_page.x(), pt_page.y())
                if w_idx is not None and w_idx != self._sel_end_word:
                    self._sel_end_word = w_idx
                    self.viewport().update()
        else:
            # Change cursor if hovering a link
            hit_page, pt_page = self._viewport_to_page(pos)
            if hit_page >= 0 and pt_page is not None:
                links = self.backend.links(hit_page)
                hovering_link = any(l.rect[0] <= pt_page.x() <= l.rect[2] and l.rect[1] <= pt_page.y() <= l.rect[3] for l in links)
                self.viewport().setCursor(Qt.PointingHandCursor if hovering_link else Qt.IBeamCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._is_selecting:
            self._is_selecting = False
            if self._sel_page >= 0 and self._sel_start_word >= 0:
                text = self.text_layer.get_selection_text(self._sel_page, self._sel_start_word, self._sel_end_word)
                rects = self.text_layer.get_selection_rects(self._sel_page, self._sel_start_word, self._sel_end_word)
                if text.strip():
                    self.text_selected.emit(self._sel_page, text, rects)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        hit_page, pt_page = self._viewport_to_page(event.position())
        if hit_page >= 0 and pt_page is not None:
            w_idx = self.text_layer.hit_test(hit_page, pt_page.x(), pt_page.y())
            if w_idx is not None:
                self._sel_page = hit_page
                s, e = self.text_layer.select_word(hit_page, w_idx)
                self._sel_start_word, self._sel_end_word = s, e
                self.viewport().update()
                text = self.text_layer.get_selection_text(hit_page, s, e)
                rects = self.text_layer.get_selection_rects(hit_page, s, e)
                self.text_selected.emit(hit_page, text, rects)

    def _clear_selection(self) -> None:
        self._sel_page = -1
        self._sel_start_word = -1
        self._sel_end_word = -1
        self.viewport().update()

    def _handle_link(self, link: Link) -> None:
        if link.target_page is not None:
            self.goto_page(link.target_page)
        elif link.target_uri:
            # Confirm before opening external links
            res = QMessageBox.question(
                self,
                "Open External Link?",
                f"Do you want to open this link in your web browser?\n\n{link.target_uri}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if res == QMessageBox.Yes:
                from booklib.utils.fileops import open_file
                open_file(link.target_uri)
        self.link_clicked.emit(link)

    def _viewport_to_page(self, pos: QPointF) -> tuple[int, QPointF | None]:
        visible = self._get_visible_pages()
        for pno, rect in visible:
            if rect.contains(int(pos.x()), int(pos.y())):
                pw, ph = self.backend.get_page_size(pno)
                sx = pw / rect.width() if rect.width() > 0 else 1.0
                sy = ph / rect.height() if rect.height() > 0 else 1.0
                px = (pos.x() - rect.left()) * sx
                py = (pos.y() - rect.top()) * sy
                return (pno, QPointF(px, py))
        return (-1, None)
