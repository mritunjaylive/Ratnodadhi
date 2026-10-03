"""
reader/backend.py – DocumentBackend protocol, Locator, and geometric data types.

The reader UI interacts ONLY with DocumentBackend; it never imports PyMuPDF directly.
This cleanly isolates the rendering engine behind a testable, swappable interface.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable

from PySide6.QtGui import QImage


@dataclass
class Locator:
    """
    Layout-independent reading position or anchor locator.
    - PDF: {"t": "pdf", "page": int, "y": float}
    - Reflowable: {"t": "flow", "chapter": int, "frac": float, "quote": str, "tok": int}
    """
    t: str = "pdf"
    page: int | None = None
    y: float | None = None
    chapter: int | None = None
    frac: float | None = None
    quote: str | None = None
    tok: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Locator:
        return cls(
            t=d.get("t", "pdf"),
            page=d.get("page"),
            y=d.get("y"),
            chapter=d.get("chapter"),
            frac=d.get("frac"),
            quote=d.get("quote"),
            tok=d.get("tok"),
        )

    @classmethod
    def from_json(cls, s: str) -> Locator:
        try:
            d = json.loads(s)
            if isinstance(d, dict):
                return cls.from_dict(d)
        except Exception:
            pass
        return cls(t="pdf", page=0, y=0.0)


@dataclass
class TextWord:
    """Single word bounding box and reading-order position on a page."""
    rect: tuple[float, float, float, float]  # x0, y0, x1, y1
    text: str
    block_num: int = 0
    line_num: int = 0
    word_num: int = 0


@dataclass
class Hit:
    """Search hit in a document."""
    page: int
    rects: list[tuple[float, float, float, float]]
    text: str = ""


@dataclass
class Link:
    """Clickable link hotspot on a page."""
    rect: tuple[float, float, float, float]
    target_page: int | None = None
    target_uri: str | None = None


@dataclass
class TocEntry:
    """Table of contents item."""
    level: int
    title: str
    page: int
    locator: Locator | None = None


@runtime_checkable
class DocumentBackend(Protocol):
    """Protocol for pluggable document engines (PyMuPDF, Qt PDF, etc.)."""

    is_reflowable: bool
    page_count: int
    is_encrypted: bool

    def open(self, path: str, password: str | None = None) -> bool:
        """Open document at path, optionally with password. Return True if opened."""
        ...

    def authenticate(self, password: str) -> bool:
        """Provide password for encrypted document. Return True if unlocked."""
        ...

    def layout(self, width: int, height: int, font_size: float) -> None:
        """Reflow document for given dimensions and font size (no-op for fixed layout)."""
        ...

    def get_page_size(self, page: int) -> tuple[float, float]:
        """Return (width, height) of page in points."""
        ...

    def toc(self) -> list[TocEntry]:
        """Return table of contents entries."""
        ...

    def render(
        self,
        page: int,
        zoom: float,
        dpr: float = 1.0,
        invert: bool = False,
        sepia: bool = False,
    ) -> QImage:
        """Render a page to a QImage."""
        ...

    def words(self, page: int) -> list[TextWord]:
        """Return words with bounding boxes on the page in reading order."""
        ...

    def links(self, page: int) -> list[Link]:
        """Return links on the page."""
        ...

    def search(self, text: str) -> list[Hit]:
        """Search text across document and return list of hits."""
        ...

    def locator_for(self, page: int, y: float) -> Locator:
        """Generate a layout-independent locator for given page and vertical fraction."""
        ...

    def page_for(self, locator: Locator) -> tuple[int, float]:
        """Resolve a locator to (page_index, y_fraction)."""
        ...

    def close(self) -> None:
        """Close document and release all resources."""
        ...
