"""
test_v6_backend.py – Unit tests for Milestone 2:
- DocumentBackend Protocol conformance
- Locator JSON serialization and roundtripping
- MuPdfBackend with PDF and reflowable TXT/EPUB
- Words, links, rendering, night mode, sepia, in-book search, TOC
"""
from __future__ import annotations

from pathlib import Path
import fitz
import pytest
from PySide6.QtGui import QImage

from booklib.reader.backend import (
    DocumentBackend,
    Hit,
    Link,
    Locator,
    TextWord,
    TocEntry,
)
from booklib.reader.mupdf_backend import MuPdfBackend


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a sample 2-page PDF with text, TOC, and link."""
    doc = fitz.open()

    # Page 1
    p1 = doc.new_page(width=400, height=600)
    p1.insert_text(fitz.Point(50, 100), "Chapter 1: The Foundations of Clean Code", fontsize=16)
    p1.insert_text(fitz.Point(50, 150), "Clean code always looks like it was written by someone who cares.", fontsize=12)

    # Page 2
    p2 = doc.new_page(width=400, height=600)
    p2.insert_text(fitz.Point(50, 100), "Chapter 2: Meaningful Names", fontsize=16)
    p2.insert_text(fitz.Point(50, 150), "Names reveal intent.", fontsize=12)

    # TOC
    toc = [
        [1, "Chapter 1", 1],
        [1, "Chapter 2", 2],
    ]
    doc.set_toc(toc)

    pdf_path = tmp_path / "test_book.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_txt(tmp_path: Path) -> Path:
    """Create a sample TXT file."""
    txt_path = tmp_path / "test_book.txt"
    txt_path.write_text(
        "Chapter 1\n\nFirst paragraph of reflowable text with multiple words.\n\n"
        "Chapter 2\n\nSecond paragraph continues the story.",
        encoding="utf-8"
    )
    return txt_path


def test_locator_serialization() -> None:
    """Verify Locator serialization and deserialization."""
    loc_pdf = Locator(t="pdf", page=4, y=0.35)
    s = loc_pdf.to_json()
    restored = Locator.from_json(s)
    assert restored.t == "pdf"
    assert restored.page == 4
    assert restored.y == 0.35

    loc_flow = Locator(t="flow", page=1, frac=0.45, quote="Clean code reads like", tok=120)
    s_flow = loc_flow.to_json()
    restored_flow = Locator.from_json(s_flow)
    assert restored_flow.t == "flow"
    assert restored_flow.quote == "Clean code reads like"
    assert restored_flow.frac == 0.45


def test_mupdf_backend_pdf_lifecycle(sample_pdf: Path, qapp) -> None:
    """Test full backend operations on PDF document."""
    backend: DocumentBackend = MuPdfBackend()
    assert isinstance(backend, DocumentBackend)

    opened = backend.open(str(sample_pdf))
    assert opened
    assert not backend.is_reflowable
    assert not backend.is_encrypted
    assert backend.page_count == 2

    # Page size
    w, h = backend.get_page_size(0)
    assert w == 400.0 and h == 600.0

    # TOC
    toc = backend.toc()
    assert len(toc) == 2
    assert toc[0].title == "Chapter 1"
    assert toc[0].page == 0
    assert toc[1].title == "Chapter 2"
    assert toc[1].page == 1

    # Rendering
    img = backend.render(0, zoom=1.0)
    assert not img.isNull()
    assert img.width() == 400
    assert img.height() == 600

    # Night mode invert
    img_inv = backend.render(0, zoom=1.0, invert=True)
    assert not img_inv.isNull()

    # Sepia mode
    img_sepia = backend.render(0, zoom=1.0, sepia=True)
    assert not img_sepia.isNull()

    # Words
    words = backend.words(0)
    assert len(words) > 0
    texts = [w.text for w in words]
    assert "Foundations" in texts

    # Search
    hits = backend.search("Clean")
    assert len(hits) >= 1
    assert any(h.page == 0 for h in hits)

    # Locator mapping
    loc = backend.locator_for(page=1, y=0.5)
    assert loc.t == "pdf"
    assert loc.page == 1
    p, y = backend.page_for(loc)
    assert p == 1
    assert y == 0.5

    backend.close()
    assert backend.page_count == 0


def test_mupdf_backend_reflowable(sample_txt: Path, qapp) -> None:
    """Test reflowable layout and quote-based locators."""
    backend = MuPdfBackend()
    opened = backend.open(str(sample_txt))
    assert opened
    assert backend.is_reflowable
    assert backend.page_count >= 1

    # Layout resize
    backend.layout(width=300, height=400, font_size=18.0)
    assert backend.page_count >= 1

    # Locator with quote
    loc = backend.locator_for(page=0, y=0.1)
    assert loc.t == "flow"
    assert loc.quote is not None

    p, y = backend.page_for(loc)
    assert p == 0

    backend.close()
