"""
tests/test_v6_fulltext.py – Tests for Milestone 9 & 9b:
- Full-text normalization, extraction, chunker
- FullTextStore schema, FTS5 contentless index, incremental vacuum
- Query builder and in-book search with BM25 ranking and snippets
- Storage limits, trim by recency, and scheduler pause rules
"""
import sqlite3
from pathlib import Path
import fitz
import pytest

from booklib.fulltext.chunker import Chunk, chunk_sections
from booklib.fulltext.extract import extract_document_sections
from booklib.fulltext.normalize import normalize_text
from booklib.fulltext.query import build_fts5_query, search_inside_books
from booklib.fulltext.scheduler import FullTextIndexScheduler
from booklib.fulltext.snippets import make_snippet
from booklib.fulltext.store import FullTextStore
from booklib.jobs.manager import JobManager


# ── 1. Normalization Tests ────────────────────────────────────────────────────

def test_normalize_text():
    raw = "The archi-\n  tecture   of   the \tsystem.\n\n\n\nNext paragraph."
    norm = normalize_text(raw)
    assert "architecture" in norm
    assert "   " not in norm
    assert "\n\n\n" not in norm
    assert "Next paragraph." in norm


# ── 2. Chunker Tests ─────────────────────────────────────────────────────────

def test_chunk_sections():
    sections = [
        {"page": 0, "chapter": 0, "text": "Paragraph one.\n\nParagraph two with more details."},
        {"page": 1, "chapter": 0, "text": "Paragraph three starts here."},
    ]
    chunks = chunk_sections(book_id=42, sections=sections, target_tokens=5, overlap_tokens=2)
    assert len(chunks) >= 2
    assert all(isinstance(c, Chunk) for c in chunks)
    assert chunks[0].book_id == 42
    assert chunks[0].token_start == 0
    assert chunks[0].token_end >= chunks[0].token_start


# ── 3. Extraction Tests ──────────────────────────────────────────────────────

def test_extract_document_sections(tmp_path: Path):
    # PDF
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((50, 72), "First page content about distributed systems and cloud architecture patterns in practice.")
    p2 = doc.new_page()
    p2.insert_text((50, 72), "Second page content about advanced data structures and algorithmic complexity theory.")
    pdf_path = tmp_path / "doc.pdf"
    doc.save(str(pdf_path))
    doc.close()

    res = extract_document_sections(str(pdf_path), "pdf")
    assert len(res["sections"]) == 2
    assert "distributed systems" in res["sections"][0]["text"]
    assert "data structures" in res["sections"][1]["text"]
    assert res["total_chars"] > 50
    assert res["is_no_text"] is False

    # Scanned / empty PDF
    empty_doc = fitz.open()
    empty_doc.new_page()
    empty_pdf = tmp_path / "empty.pdf"
    empty_doc.save(str(empty_pdf))
    empty_doc.close()

    res_empty = extract_document_sections(str(empty_pdf), "pdf")
    assert res_empty["is_no_text"] is True

    # TXT
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("Simple text file line 1\n\nLine 2 content", encoding="utf-8")
    res_txt = extract_document_sections(str(txt_path), "txt")
    assert len(res_txt["sections"]) >= 1
    assert "Simple text file" in res_txt["sections"][0]["text"]


# ── 4. FullTextStore CRUD & Contentless Delete ────────────────────────────────

def test_fulltext_store_crud(tmp_path: Path):
    store_path = tmp_path / "fulltext_test.db"
    store = FullTextStore(store_path)
    conn = store.connect()

    # Store chunks
    chunks = [
        Chunk(
            book_id=1,
            chapter_index=0,
            page_number=1,
            chunk_index=0,
            token_start=0,
            token_end=10,
            char_count=50,
            text="Quantum computing utilizes quantum entanglement.",
        ),
        Chunk(
            book_id=1,
            chapter_index=0,
            page_number=2,
            chunk_index=1,
            token_start=11,
            token_end=20,
            char_count=45,
            text="Superposition allows simultaneous states.",
        ),
    ]

    stored_count = store.store_book_chunks(1, chunks)
    assert stored_count == 2
    assert store.get_indexed_book_ids() == {1}

    # Verify FTS contentless query
    fts_rows = conn.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'entanglement'").fetchall()
    assert len(fts_rows) == 1

    # Verify contentless delete
    deleted = store.delete_book_chunks(1)
    assert deleted == 2
    assert store.get_indexed_book_ids() == set()

    fts_rows_after = conn.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'entanglement'").fetchall()
    assert len(fts_rows_after) == 0

    store.close()


# ── 5. Query Builder & In-Book Search Tests ──────────────────────────────────

def test_query_builder():
    assert build_fts5_query('python programming') == '"python" "programming"'
    assert build_fts5_query('"clean architecture"') == '"clean architecture"'
    assert 'NOT "legacy"' in build_fts5_query('python -legacy')
    assert build_fts5_query('algo*') == '"algo"*'
    assert build_fts5_query('') == ''
    assert build_fts5_query(':::???') == ''


def test_search_inside_books(tmp_path: Path):
    store_path = tmp_path / "search_test.db"
    store = FullTextStore(store_path)

    # Book 1 chunks
    c1 = [
        Chunk(1, 0, 10, 0, 0, 5, 40, "Fast algorithms and asymptotic complexity."),
        Chunk(1, 0, 11, 1, 6, 12, 45, "Binary search trees and balanced red black trees."),
    ]
    # Book 2 chunks
    c2 = [
        Chunk(2, 0, 5, 0, 0, 5, 40, "Deep neural networks and backpropagation."),
        Chunk(2, 0, 6, 1, 6, 12, 45, "Convolutional layers for image classification."),
    ]
    store.store_book_chunks(1, c1)
    store.store_book_chunks(2, c2)

    # Search for "complexity"
    results1 = search_inside_books(store, "complexity")
    assert len(results1) == 1
    assert results1[0].book_id == 1
    assert results1[0].total_hits == 1
    assert results1[0].hits[0].page_number == 10

    # Search for "trees"
    results2 = search_inside_books(store, "trees")
    assert len(results2) == 1
    assert results2[0].book_id == 1
    assert "<b>trees</b>" in results2[0].hits[0].snippet.lower()

    # Search with book_ids filter
    results_filtered = search_inside_books(store, "networks", book_ids=[1])
    assert len(results_filtered) == 0

    results_found = search_inside_books(store, "networks", book_ids=[2])
    assert len(results_found) == 1
    assert results_found[0].book_id == 2

    store.close()


# ── 6. Snippet Highlighting Tests ────────────────────────────────────────────

def test_snippets_formatting():
    text = "The preliminary investigation revealed several fundamental flaws in security."
    snippet = make_snippet(text, "flaws")
    assert "<b>flaws</b>" in snippet
    assert "preliminary investigation" in snippet


# ── 7. Storage Limit, Trim, and Compact Tests ────────────────────────────────

def test_index_trim_and_compact(tmp_path: Path):
    store_path = tmp_path / "trim_test.db"
    store = FullTextStore(store_path)
    store.connect()

    # Create dummy library database
    lib_path = tmp_path / "library.db"
    lib_conn = sqlite3.connect(str(lib_path))
    lib_conn.row_factory = sqlite3.Row
    with lib_conn:
        lib_conn.execute(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                title TEXT,
                fts_state TEXT,
                text_chars INTEGER,
                fts_indexed_at TEXT,
                last_opened_at TEXT
            )
            """
        )
        # Book 1: opened today
        lib_conn.execute(
            "INSERT INTO books (id, title, fts_state, last_opened_at) VALUES (1, 'Recent', 'indexed', datetime('now'))"
        )
        # Book 2: never opened
        lib_conn.execute(
            "INSERT INTO books (id, title, fts_state, last_opened_at) VALUES (2, 'Never Opened', 'indexed', NULL)"
        )
        # Book 3: opened 120 days ago
        lib_conn.execute(
            "INSERT INTO books (id, title, fts_state, last_opened_at) VALUES (3, 'Old', 'indexed', datetime('now', '-120 days'))"
        )

    # Insert dummy chunks in store
    store.store_book_chunks(1, [Chunk(1, 0, 1, 0, 0, 1, 10, "Recent text")])
    store.store_book_chunks(2, [Chunk(2, 0, 1, 0, 0, 1, 10, "Never opened text")])
    store.store_book_chunks(3, [Chunk(3, 0, 1, 0, 0, 1, 10, "Old text")])

    # Trim books older than 90 days
    trimmed = store.trim_old_index(lib_conn, max_days=90)
    assert trimmed == 2  # Book 2 (never opened) and Book 3 (120 days ago)

    # Book 1 should still be indexed
    assert store.get_indexed_book_ids() == {1}
    row1 = lib_conn.execute("SELECT fts_state FROM books WHERE id = 1").fetchone()
    assert row1["fts_state"] == "indexed"

    row2 = lib_conn.execute("SELECT fts_state FROM books WHERE id = 2").fetchone()
    assert row2["fts_state"] is None

    # Compact test
    store.compact()
    assert store.get_size_bytes() > 0

    lib_conn.close()
    store.close()


# ── 8. Scheduler Pause Conditions ────────────────────────────────────────────

def test_scheduler_pause_conditions(tmp_path: Path):
    store_path = tmp_path / "sched_test.db"
    store = FullTextStore(store_path)
    store.connect()

    jm = JobManager()
    sched = FullTextIndexScheduler(db_conn_supplier=lambda: None, job_manager=jm, store=store)
    sched.pause_on_battery = False

    # Default: running / no pause
    assert sched.check_pause_conditions() is None

    # Pause on render
    sched.set_rendering_active(True)
    assert sched.check_pause_conditions() == "rendering"
    sched.set_rendering_active(False)

    # Size limit pause
    sched.limit_bytes = 10  # very low limit
    assert sched.check_pause_conditions() == "size_limit"

    store.close()
