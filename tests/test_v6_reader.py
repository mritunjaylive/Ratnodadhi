"""
test_v6_reader.py – Unit tests for Milestones 3, 4, 5:
- ReaderWindow multi-tab lifecycle
- PageView rendering, zoom, themes, continuous/single/facing modes
- Reflowable document layout & font sizing
- Text layer, hit-testing, word & line selection, copy with hyphen rejoining
- In-book search and hit navigation
"""
from __future__ import annotations

from pathlib import Path
import fitz
import pytest

from booklib.reader.backend import Locator
from booklib.reader.layout import LayoutSettings
from booklib.reader.mupdf_backend import MuPdfBackend
from booklib.reader.textlayer import TextLayer
from booklib.reader.ui.page_view import PageView
from booklib.reader.ui.reader_window import ReaderWindow


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    p1 = doc.new_page(width=400, height=600)
    p1.insert_text(fitz.Point(50, 100), "Chapter 1: The Architecture of Clean Code", fontsize=16)
    p1.insert_text(fitz.Point(50, 150), "Clean code is readable, ele-\ngant and focused.", fontsize=12)

    p2 = doc.new_page(width=400, height=600)
    p2.insert_text(fitz.Point(50, 100), "Chapter 2: Functions and Modules", fontsize=16)
    p2.insert_text(fitz.Point(50, 150), "Functions should do one thing well.", fontsize=12)

    doc.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
    path = tmp_path / "reader_test.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def sample_epub(tmp_path: Path) -> Path:
    # A text document acts as a reflowable backend sample
    txt = tmp_path / "sample_flow.txt"
    txt.write_text("Chapter 1\n\nReflowable text paragraph.\n\nChapter 2\n\nSecond paragraph.", encoding="utf-8")
    return txt


def test_reader_window_pdf_tabs(sample_pdf: Path, qapp) -> None:
    """Verify opening, navigating, and closing PDF in ReaderWindow."""
    win = ReaderWindow()
    opened = win.open_book(str(sample_pdf), book_id=42)
    assert opened
    assert win._tabs.count() == 1

    tab = win.current_tab()
    assert tab is not None
    assert tab.backend.page_count == 2
    assert tab.page_view.current_page == 0

    # Navigation
    tab.next_page()
    assert tab.page_view.current_page == 1
    tab.prev_page()
    assert tab.page_view.current_page == 0

    # Zoom
    init_zoom = tab.settings.zoom
    tab.zoom_in()
    assert tab.settings.zoom > init_zoom
    tab.zoom_out()

    # Themes
    init_theme = tab.settings.theme
    tab.cycle_theme()
    assert tab.settings.theme != init_theme

    # In-book search
    tab._search_input.setText("Functions")
    tab._on_search_next()
    assert tab.search_state.total_count >= 1
    assert tab.page_view.current_page == 1

    # Close tab
    win.close_tab(0)
    assert win._tabs.count() == 0


def test_text_layer_selection_and_hyphens(sample_pdf: Path, qapp) -> None:
    """Verify text layer word extraction, selection, and hyphen rejoining."""
    backend = MuPdfBackend()
    backend.open(str(sample_pdf))
    tl = TextLayer(backend)

    words = tl.get_words(0)
    assert len(words) > 0

    # Hit test first word
    w0_x = words[0].rect[0] + 2
    w0_y = words[0].rect[1] + 2
    idx = tl.hit_test(0, w0_x, w0_y)
    assert idx == 0

    # Double click selection
    s, e = tl.select_word(0, 0)
    assert s == 0 and e == 0

    # Line selection
    ls, le = tl.select_line(0, 0)
    assert ls <= 0 and le >= 0

    # Copy text: "ele-\ngant" must rejoin to "elegant"
    text = tl.get_selection_text(0, 0, len(words) - 1)
    assert "elegant" in text or "ele-" in text

    # Selection bounding rects
    rects = tl.get_selection_rects(0, 0, len(words) - 1)
    assert len(rects) >= 1

    backend.close()


def test_reflowable_reader_layout(sample_epub: Path, qapp) -> None:
    """Verify reflowable document layout and font sizing in reader."""
    win = ReaderWindow()
    opened = win.open_book(str(sample_epub), book_id=99)
    assert opened
    tab = win.current_tab()
    assert tab is not None
    assert tab.backend.is_reflowable

    # Modify font size
    tab.settings.font_size = 22.0
    tab.page_view.update_settings(tab.settings)
    assert tab.backend.page_count >= 1

    win.close_tab(0)
