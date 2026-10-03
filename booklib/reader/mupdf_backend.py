"""
reader/mupdf_backend.py – PyMuPDF (fitz) implementation of DocumentBackend.

Supports PDF, EPUB, MOBI, FB2, CBZ, and TXT.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from PySide6.QtGui import QColor, QImage, QPainter

from booklib.reader.backend import Hit, Link, Locator, TextWord, TocEntry

logger = logging.getLogger(__name__)

_REFLOWABLE_EXTS = {".epub", ".mobi", ".fb2", ".txt"}


class MuPdfBackend:
    """DocumentBackend implemented with PyMuPDF."""

    def __init__(self) -> None:
        self._doc: fitz.Document | None = None
        self._path: str = ""
        self.is_reflowable: bool = False

    @property
    def page_count(self) -> int:
        return len(self._doc) if self._doc is not None else 0

    @property
    def is_encrypted(self) -> bool:
        return bool(self._doc and self._doc.is_encrypted)

    def open(self, path: str, password: str | None = None) -> bool:
        """Open a file at path, optionally with password."""
        self.close()
        self._path = path
        ext = Path(path).suffix.lower()

        try:
            self._doc = fitz.open(path)
            self.is_reflowable = ext in _REFLOWABLE_EXTS or getattr(self._doc, "is_reflowable", False)

            if self._doc.is_encrypted:
                if password:
                    res = self._doc.authenticate(password)
                    return bool(res)
                return False  # needs password prompt
            return True
        except Exception as exc:
            logger.warning("Failed to open document %s with MuPDF: %s", path, exc)
            self._doc = None
            return False

    def authenticate(self, password: str) -> bool:
        """Authenticate password-protected document."""
        if self._doc is None or not self._doc.is_encrypted:
            return True
        try:
            return bool(self._doc.authenticate(password))
        except Exception as exc:
            logger.warning("Error authenticating document: %s", exc)
            return False

    def layout(self, width: int, height: int, font_size: float) -> None:
        """Reflow reflowable documents (EPUB, TXT, MOBI, FB2)."""
        if self._doc is None or not self.is_reflowable:
            return
        try:
            w = max(int(width), 200)
            h = max(int(height), 200)
            rect = fitz.Rect(0, 0, w, h)
            self._doc.layout(rect=rect, fontsize=float(font_size))
        except Exception as exc:
            logger.warning("Layout reflow error: %s", exc)

    def get_page_size(self, page: int) -> tuple[float, float]:
        """Return (width, height) of page in points."""
        if self._doc is None or page < 0 or page >= len(self._doc):
            return (0.0, 0.0)
        try:
            p = self._doc[page]
            return (float(p.rect.width), float(p.rect.height))
        except Exception:
            return (0.0, 0.0)

    def toc(self) -> list[TocEntry]:
        """Return table of contents entries."""
        if self._doc is None:
            return []
        try:
            raw_toc = self._doc.get_toc()  # list of [lvl, title, pno]
            entries: list[TocEntry] = []
            for item in raw_toc:
                lvl, title, pno = item[0], str(item[1]), int(item[2])
                page_idx = max(0, pno - 1)
                loc = Locator(
                    t="flow" if self.is_reflowable else "pdf",
                    page=page_idx,
                    y=0.0,
                )
                entries.append(TocEntry(level=lvl, title=title, page=page_idx, locator=loc))
            return entries
        except Exception as exc:
            logger.warning("Failed to extract TOC: %s", exc)
            return []

    def render(
        self,
        page: int,
        zoom: float,
        dpr: float = 1.0,
        invert: bool = False,
        sepia: bool = False,
    ) -> QImage:
        """Render page at zoom * dpr to QImage."""
        if self._doc is None or page < 0 or page >= len(self._doc):
            return QImage()

        try:
            p = self._doc[page]
            scale = max(zoom * dpr, 0.05)
            mat = fitz.Matrix(scale, scale)
            pix = p.get_pixmap(matrix=mat, alpha=False)

            # Copy buffer so QImage owns the pixel memory
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()

            if invert:
                img.invertPixels()
            elif sepia:
                painter = QPainter(img)
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
                painter.fillRect(img.rect(), QColor(244, 236, 216))
                painter.end()

            return img
        except Exception as exc:
            logger.warning("Error rendering page %d: %s", page, exc)
            return QImage()

    def words(self, page: int) -> list[TextWord]:
        """Return text words in reading order with bounding boxes."""
        if self._doc is None or page < 0 or page >= len(self._doc):
            return []

        try:
            p = self._doc[page]
            raw_words = p.get_text("words")
            result: list[TextWord] = []
            for w in raw_words:
                rect = (float(w[0]), float(w[1]), float(w[2]), float(w[3]))
                text = str(w[4])
                b = int(w[5]) if len(w) > 5 else 0
                l = int(w[6]) if len(w) > 6 else 0
                wn = int(w[7]) if len(w) > 7 else 0
                result.append(TextWord(rect=rect, text=text, block_num=b, line_num=l, word_num=wn))
            return result
        except Exception as exc:
            logger.warning("Error getting words for page %d: %s", page, exc)
            return []

    def links(self, page: int) -> list[Link]:
        """Return interactive links on the page."""
        if self._doc is None or page < 0 or page >= len(self._doc):
            return []

        try:
            p = self._doc[page]
            raw_links = p.get_links()
            res: list[Link] = []
            for l in raw_links:
                r = l.get("from")
                if r:
                    rect = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
                    res.append(Link(rect=rect, target_page=l.get("page"), target_uri=l.get("uri")))
            return res
        except Exception as exc:
            logger.warning("Error getting links for page %d: %s", page, exc)
            return []

    def search(self, text: str) -> list[Hit]:
        """Search text across all pages in document."""
        if self._doc is None or not text.strip():
            return []

        hits: list[Hit] = []
        try:
            for pno in range(len(self._doc)):
                p = self._doc[pno]
                rects = p.search_for(text)
                if rects:
                    hit_rects = [(float(r.x0), float(r.y0), float(r.x1), float(r.y1)) for r in rects]
                    hits.append(Hit(page=pno, rects=hit_rects, text=text))
        except Exception as exc:
            logger.warning("Error searching document: %s", exc)
        return hits

    def locator_for(self, page: int, y: float) -> Locator:
        """Create a layout-independent locator for given position."""
        if self._doc is None or len(self._doc) == 0:
            return Locator(t="pdf", page=page, y=y)

        if not self.is_reflowable:
            return Locator(t="pdf", page=page, y=y)

        words_list = self.words(page)
        quote = " ".join(w.text for w in words_list[:12]) if words_list else ""
        frac = float(page) / max(len(self._doc), 1)
        return Locator(t="flow", page=page, y=y, frac=frac, quote=quote)

    def page_for(self, locator: Locator) -> tuple[int, float]:
        """Map locator to (page, y)."""
        if self._doc is None or len(self._doc) == 0:
            return (0, 0.0)

        # 1. Exact page index if within bounds
        if locator.page is not None and 0 <= locator.page < len(self._doc):
            return (locator.page, locator.y or 0.0)

        # 2. Reflowable quote search if quote exists
        if self.is_reflowable and locator.quote:
            hits = self.search(locator.quote[:30])
            if hits:
                return (hits[0].page, locator.y or 0.0)

        # 3. Fraction fallback
        if locator.frac is not None:
            p = min(int(locator.frac * len(self._doc)), len(self._doc) - 1)
            return (max(0, p), locator.y or 0.0)

        return (0, 0.0)

    def close(self) -> None:
        """Close document."""
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None
