"""
tests/test_v6_annotations.py – Tests for bookmarks, annotations anchoring, CRUD, exports, and PDF annotating.
"""
import json
import sqlite3
from pathlib import Path
import fitz
import pytest

from booklib.db.database import Database
from booklib.reader.annotations import (
    anchor,
    add_annotation,
    update_annotation,
    delete_annotation,
    list_annotations,
    export_markdown,
    export_html,
    export_csv,
    export_json,
    export_annotated_pdf,
    import_pdf_highlights,
)
from booklib.reader.backend import Locator
from booklib.reader.bookmarks import (
    add_bookmark,
    list_bookmarks,
    rename_bookmark,
    delete_bookmark,
    get_bookmarked_pages,
)


@pytest.fixture
def test_db(tmp_path: Path):
    db_path = tmp_path / "test_annot.db"
    db = Database(db_path)
    conn = db.connect()
    # Insert dummy folder and book
    with conn:
        conn.execute("INSERT INTO folders (id, path) VALUES (1, '/books')")
        conn.execute(
            """
            INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime, title, author, status)
            VALUES (1, 1, '/books/b.pdf', 'b.pdf', 'pdf', 1024, 0, 'Test Masterpiece', 'Ada Lovelace', 'want')
            """
        )
    return db


# ── 1. Anchoring Algorithm Tests ─────────────────────────────────────────────

def test_anchor_exact_match():
    text = "The quick brown fox jumps over the lazy dog in the tranquil forest"
    words = text.split()
    quote = "brown fox jumps"

    match = anchor(words, quote)
    assert match is not None
    start, end = match
    assert words[start:end + 1] == ["brown", "fox", "jumps"]


def test_anchor_prefix_suffix_disambiguation():
    # "apple orange" appears twice:
    # 1. "red apple orange green"
    # 2. "blue apple orange yellow"
    text = "red apple orange green other stuff blue apple orange yellow end"
    words = text.split()

    # Search with prefix "blue" and suffix "yellow"
    match = anchor(words, quote="apple orange", prefix="blue", suffix="yellow")
    assert match is not None
    start, end = match
    assert words[start - 1] == "blue"
    assert words[end + 1] == "yellow"


def test_anchor_fuzzy_match():
    text = "The architecture of computing systems is constantly evolving"
    words = text.split()
    # Slight typographical difference: "architectur of computing system" (close enough >= 0.85)
    quote = "architectur of computing system"

    match = anchor(words, quote)
    assert match is not None
    start, end = match
    assert words[start] == "The" or words[start] == "architecture"


def test_anchor_orphaned():
    text = "Call me Ishmael. Some years ago..."
    words = text.split()
    quote = "completely unrelated sentence that never occurs here"

    match = anchor(words, quote)
    assert match is None


# ── 2. Bookmarks CRUD Tests ──────────────────────────────────────────────────

def test_bookmarks_crud(test_db):
    conn = test_db.conn
    loc1 = Locator(page=2, chapter=1, tok=100)
    loc2 = Locator(page=5, chapter=2, tok=500)

    # Add
    bm1_id = add_bookmark(conn, book_id=1, locator=loc1, label="First bookmark", snippet="Quick brown fox")
    bm2_id = add_bookmark(conn, book_id=1, locator=loc2, label="Second bookmark", snippet="Jumping dog")
    assert bm1_id > 0
    assert bm2_id > 0

    # List
    bms = list_bookmarks(conn, 1)
    assert len(bms) == 2
    assert bms[0]["label"] == "First bookmark"
    assert bms[0]["locator_obj"].page == 2

    # Bookmarked pages
    pages = get_bookmarked_pages(conn, 1)
    assert pages == {2, 5}

    # Rename
    rename_bookmark(conn, bm1_id, "Updated Label")
    bms = list_bookmarks(conn, 1)
    assert bms[0]["label"] == "Updated Label"

    # Delete
    delete_bookmark(conn, bm1_id)
    pages = get_bookmarked_pages(conn, 1)
    assert pages == {5}


# ── 3. Annotations CRUD & FTS Tests ──────────────────────────────────────────

def test_annotations_crud_and_fts(test_db):
    conn = test_db.conn
    loc = Locator(page=10, chapter=2, tok=42)

    # Add
    a1_id = add_annotation(
        conn,
        book_id=1,
        kind="highlight",
        color="yellow",
        quote="Simplicity is prerequisite for reliability.",
        prefix="Remember that ",
        suffix=" Always.",
        locator=loc,
        note="Edsger Dijkstra quote",
    )
    a2_id = add_annotation(
        conn,
        book_id=1,
        kind="note",
        color="green",
        quote="Premature optimization is the root of all evil.",
        locator=loc,
        note="Donald Knuth famous line",
    )
    assert a1_id > 0
    assert a2_id > 0

    # List all
    all_annots = list_annotations(conn, book_id=1)
    assert len(all_annots) == 2
    assert all_annots[0]["book_title"] == "Test Masterpiece"

    # Filter by color
    yellow_annots = list_annotations(conn, book_id=1, color="yellow")
    assert len(yellow_annots) == 1
    assert yellow_annots[0]["id"] == a1_id

    # Filter by kind
    notes = list_annotations(conn, book_id=1, kind="note")
    assert len(notes) == 1
    assert notes[0]["id"] == a2_id

    # FTS search across quotes and notes
    fts_results = list_annotations(conn, query="Dijkstra")
    assert len(fts_results) == 1
    assert fts_results[0]["id"] == a1_id

    fts_results2 = list_annotations(conn, query="optimization")
    assert len(fts_results2) == 1
    assert fts_results2[0]["id"] == a2_id

    # Update
    update_annotation(conn, a1_id, note="Updated Dijkstra note", color="blue")
    updated = list_annotations(conn, book_id=1, color="blue")
    assert len(updated) == 1
    assert updated[0]["note"] == "Updated Dijkstra note"

    # Delete
    delete_annotation(conn, a2_id)
    remaining = list_annotations(conn, book_id=1)
    assert len(remaining) == 1
    assert remaining[0]["id"] == a1_id


# ── 4. Export Formats Tests ──────────────────────────────────────────────────

def test_annotations_exports(test_db):
    conn = test_db.conn
    loc = Locator(page=3)
    add_annotation(
        conn,
        book_id=1,
        kind="highlight",
        color="pink",
        quote="First principles thinking.",
        locator=loc,
        note="Key takeaway",
    )
    annots = list_annotations(conn, book_id=1)

    # Markdown
    md = export_markdown(annots, book_title="Great Book", author="Author Name")
    assert "# Great Book" in md
    assert "> First principles thinking." in md
    assert "**Note:** Key takeaway" in md

    # HTML
    html_out = export_html(annots, book_title="Great Book", author="Author Name")
    assert "<title>Great Book</title>" in html_out
    assert "First principles thinking." in html_out
    assert "Key takeaway" in html_out

    # CSV
    csv_out = export_csv(annots)
    assert "First principles thinking." in csv_out
    assert "Key takeaway" in csv_out

    # JSON
    json_out = export_json(annots)
    parsed = json.loads(json_out)
    assert len(parsed) == 1
    assert parsed[0]["quote"] == "First principles thinking."


# ── 5. PDF Export & Import Tests ─────────────────────────────────────────────

def test_pdf_annotated_copy_and_import(tmp_path: Path, test_db):
    # Create simple PDF using PyMuPDF
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "The quick brown fox jumps over the lazy dog.")
    src_pdf = tmp_path / "sample.pdf"
    doc.save(str(src_pdf))
    doc.close()

    conn = test_db.conn
    loc = Locator(page=0)
    add_annotation(
        conn,
        book_id=1,
        kind="highlight",
        color="yellow",
        quote="brown fox jumps",
        locator=loc,
        note="Fabulous fox",
    )
    annots = list_annotations(conn, book_id=1)

    out_pdf = tmp_path / "sample_annotated.pdf"
    ok = export_annotated_pdf(str(src_pdf), str(out_pdf), annots)
    assert ok is True
    assert out_pdf.exists()

    # Source should remain without annotations
    doc_src = fitz.open(str(src_pdf))
    assert list(doc_src[0].annots()) == []
    doc_src.close()

    # Output should have highlight annotation
    doc_out = fitz.open(str(out_pdf))
    page_out = doc_out[0]
    out_annots = list(page_out.annots())
    assert len(out_annots) >= 1
    doc_out.close()

    # Import highlights back into database
    imported_count = import_pdf_highlights(conn, book_id=1, pdf_path=str(out_pdf))
    assert imported_count >= 1
