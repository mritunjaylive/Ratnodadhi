"""
test_v3_duplicates_and_relink.py – Duplicates, user data merge, relinking, reading log, and custom covers.
"""
import io
import json
import sqlite3
from pathlib import Path
from PIL import Image

import pytest

from booklib.config import COVERS_DIR
from booklib.covers.custom import (
    process_image_bytes, restore_original_cover, save_custom_cover,
)
from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.duplicates.finder import find_duplicate_groups, make_author_key, make_title_key
from booklib.duplicates.hashing import compute_full_hash, compute_quick_hash
from booklib.duplicates.merge import merge_book_user_data


# ── Hashing Tests ────────────────────────────────────────────────────────────

def test_hashing(tmp_path: Path):
    f1 = tmp_path / "book1.pdf"
    f1.write_bytes(b"hello world" * 100)

    f2 = tmp_path / "book2.pdf"
    f2.write_bytes(b"hello world" * 100)

    f3 = tmp_path / "book3.pdf"
    f3.write_bytes(b"different content" * 100)

    # Identical files have identical quick_hash and full_hash
    qh1 = compute_quick_hash(f1)
    qh2 = compute_quick_hash(f2)
    qh3 = compute_quick_hash(f3)
    assert qh1 == qh2
    assert qh1 != qh3

    fh1 = compute_full_hash(f1)
    fh2 = compute_full_hash(f2)
    fh3 = compute_full_hash(f3)
    assert fh1 == fh2
    assert fh1 != fh3


# ── Duplicate Detection & Merge Tests ────────────────────────────────────────

def test_duplicate_finding_and_merging(tmp_path: Path):
    db = Database(tmp_path / "test_dup.db")
    conn = db.connect()
    r = Repository(conn)
    fid = r.add_folder("C:/Books")


    # Insert identical file hash duplicates
    r.upsert_book(
        folder_id=fid, path="C:/Books/copy1.pdf", filename="copy1.pdf",
        format="pdf", size_bytes=5000, file_mtime=1.0,
        title="Dune", author="Frank Herbert", publisher=None,
        year=1965, isbn="9780441172719", pages=500, genre="Sci-Fi", language="en",
        cover_path=None, quick_hash="qh_dune",
    )
    r.upsert_book(
        folder_id=fid, path="C:/Books/copy2.pdf", filename="copy2.pdf",
        format="pdf", size_bytes=5000, file_mtime=1.0,
        title="Dune", author="Frank Herbert", publisher=None,
        year=1965, isbn="9780441172719", pages=500, genre="Sci-Fi", language="en",
        cover_path=None, quick_hash="qh_dune",
    )

    # Set identical full file_hash
    conn.execute("UPDATE books SET file_hash = 'dune_full_hash'")
    conn.commit()

    # Find duplicates
    groups = find_duplicate_groups(conn)
    assert len(groups) == 1
    g = groups[0]
    assert g.level == "exact"
    assert set(g.book_ids) == {1, 2}

    # Set user data on copies
    r.set_status([1], "want")
    r.set_status([2], "read")
    r.set_rating(1, 4)
    r.set_notes(2, "Loved this classic!")

    # Merge user data into keeper (book 1)
    merge_book_user_data(conn, keeper_id=1, duplicate_ids=[2])
    conn.commit()

    # Keeper should now have 'read' status, rating 4, and the notes
    b1 = r.get_book_row(1)
    assert b1.status == "read"
    assert b1.rating == 4
    detail1 = r.get_book_detail(1)
    assert "Loved this classic!" in detail1.notes

    db.close()


def test_similar_keys():
    t1 = "The Great Gatsby (2nd Edition) [PDF]"
    t2 = "Great Gatsby"
    assert make_title_key(t1) == make_title_key(t2)

    a1 = "Fitzgerald, F. Scott"
    a2 = "F. Scott Fitzgerald"
    assert make_author_key(a1) == make_author_key(a2)


# ── Relinking Tests ──────────────────────────────────────────────────────────

def test_relink_moved_file(tmp_path: Path):
    db = Database(tmp_path / "test_relink.db")
    conn = db.connect()
    r = Repository(conn)
    fid = r.add_folder("C:/Books")

    # Insert book that then becomes missing
    bid = r.upsert_book(
        folder_id=fid, path="C:/Books/old_name.epub", filename="old_name.epub",
        format="epub", size_bytes=12345, file_mtime=1.0,
        title="My Book", author="Author", publisher=None,
        year=2020, isbn=None, pages=200, genre=None, language="en",
        cover_path=None, quick_hash="qh_12345",
    )
    r.set_status([bid], "reading")
    r.mark_missing(["C:/Books/old_name.epub"])
    db.conn.commit()

    # Find missing book by size and quick_hash
    matching = r.find_missing_by_size_and_quick_hash(12345, "qh_12345")
    assert matching == [bid]

    # Relink
    r.relink_book(bid, "C:/Books/new_name.epub", "new_name.epub", fid, 2.0, 12345)

    row = r.get_book_row(bid)
    assert row.path == "C:/Books/new_name.epub"
    assert row.is_missing is False
    assert row.status == "reading"

    db.close()


# ── Reading Log State Machine Tests ──────────────────────────────────────────

def test_reading_log_state_machine(tmp_path: Path):
    db = Database(tmp_path / "test_log.db")
    conn = db.connect()
    r = Repository(conn)
    fid = r.add_folder("C:/Books")

    bid = r.upsert_book(
        folder_id=fid, path="C:/Books/book.epub", filename="book.epub",
        format="epub", size_bytes=1000, file_mtime=1.0,
        title="Test", author="Author", publisher=None,
        year=2020, isbn=None, pages=100, genre=None, language="en",
        cover_path=None,
    )

    # 1. Set to 'reading' -> should create log row with started_on
    r.set_status([bid], "reading")
    d1 = r.get_book_detail(bid)
    assert len(d1.reading_log) == 1
    assert d1.reading_log[0]["started_on"] is not None
    assert d1.reading_log[0]["finished_on"] is None

    # 2. Set to 'read' -> should close open log row with finished_on
    r.set_status([bid], "read")
    d2 = r.get_book_detail(bid)
    assert len(d2.reading_log) == 1
    assert d2.reading_log[0]["finished_on"] is not None

    # 3. Read again -> starts a new open log row
    r.read_again(bid)
    d3 = r.get_book_detail(bid)
    assert len(d3.reading_log) == 2
    assert d3.status == "reading"

    db.close()


# ── Custom Cover Tests ───────────────────────────────────────────────────────

def test_custom_cover(tmp_path: Path):
    db = Database(tmp_path / "test_cover.db")
    conn = db.connect()
    r = Repository(conn)
    fid = r.add_folder("C:/Books")


    bid = r.upsert_book(
        folder_id=fid, path="C:/Books/b.epub", filename="b.epub",
        format="epub", size_bytes=1000, file_mtime=1.0,
        title="Cover Test", author="Author", publisher=None,
        year=2020, isbn=None, pages=100, genre=None, language="en",
        cover_path=None,
    )

    # Create test image in memory
    img = Image.new("RGB", (400, 600), color="blue")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    raw_png = buf.getvalue()

    # Process and save custom cover
    rel_path = save_custom_cover(db.conn, bid, raw_png, source="custom")
    assert rel_path.startswith("custom/")

    row = r.get_book_row(bid)
    assert row.cover_source == "custom"
    assert row.cover_path == rel_path

    # Verify custom file on disk is resized to 300px width
    saved_file = COVERS_DIR / rel_path
    assert saved_file.exists()
    with Image.open(saved_file) as saved_img:
        assert saved_img.size[0] == 300

    # Restore original cover
    restore_original_cover(db.conn, bid)
    row_restored = r.get_book_row(bid)
    assert row_restored.cover_source in ("file", "placeholder")
    # Custom file should be cleaned up
    assert not saved_file.exists()

    db.close()
