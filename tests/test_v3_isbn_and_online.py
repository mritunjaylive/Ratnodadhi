"""
test_v3_isbn_and_online.py – ISBN validation, online provider parsing, scoring, merging, and undo.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from booklib.metadata.isbn_scan import (
    clean_isbn, isbn_10_to_13, validate_isbn_10, validate_isbn_13,
)
from booklib.metadata.online.googlebooks import GoogleBooksProvider
from booklib.metadata.online.merge import (
    apply_candidate, clean_authors, clean_genres, undo_batch,
)
from booklib.metadata.online.models import Candidate
from booklib.metadata.online.openlibrary import OpenLibraryProvider
from booklib.metadata.online.scoring import decide_candidates, score_candidate


# ── ISBN Tests ───────────────────────────────────────────────────────────────

def test_isbn_validation():
    # Valid ISBN-10
    assert validate_isbn_10("0471958697") is True
    assert validate_isbn_10("0123456788") is False


    # Valid ISBN-10 with X
    assert validate_isbn_10("080442957X") is True

    # Valid ISBN-13
    assert validate_isbn_13("9780470059029") is True
    assert validate_isbn_13("9780470059028") is False  # bad check digit

    # clean_isbn with hyphens and spaces
    assert clean_isbn("ISBN 978-0-470-05902-9") == "9780470059029"
    assert clean_isbn("0-8044-2957-X") == "080442957X"
    assert clean_isbn("invalid-isbn") is None

    # ISBN-10 to 13 conversion
    assert isbn_10_to_13("0471958697") == "9780471958697"


# ── Provider Parsing Tests ───────────────────────────────────────────────────

def test_openlibrary_isbn_parsing():
    ol = OpenLibraryProvider()
    fake_json = {
        "ISBN:9780140328721": {
            "title": "Fantastic Mr Fox",
            "authors": [{"name": "Roald Dahl"}],
            "publishers": [{"name": "Puffin"}],
            "publish_date": "1988",
            "number_of_pages": 96,
            "subjects": [{"name": "Foxes"}, {"name": "Accessible book"}],
            "cover": {"large": "https://covers.openlibrary.org/b/id/123-L.jpg"},
            "key": "/books/OL123M",
        }
    }

    # Test parser with mock http client
    class MockHttp:
        def get_json(self, url, **kwargs):
            return fake_json

    ol.http = MockHttp()
    candidates = ol.lookup_isbn("978-0-14-032872-1")
    assert len(candidates) == 1
    c = candidates[0]
    assert c.title == "Fantastic Mr Fox"
    assert c.authors == ["Roald Dahl"]
    assert c.publisher == "Puffin"
    assert c.year == 1988
    assert c.pages == 96
    assert c.cover_url == "https://covers.openlibrary.org/b/id/123-L.jpg"


def test_googlebooks_parsing():
    gb = GoogleBooksProvider()
    fake_json = {
        "items": [
            {
                "id": "vol_abc",
                "volumeInfo": {
                    "title": "Clean Code",
                    "authors": ["Robert C. Martin"],
                    "publisher": "Prentice Hall",
                    "publishedDate": "2008-08-01",
                    "pageCount": 464,
                    "categories": ["Computers / Programming / General"],
                    "industryIdentifiers": [
                        {"type": "ISBN_10", "identifier": "0132350882"},
                        {"type": "ISBN_13", "identifier": "9780132350884"},
                    ],
                    "imageLinks": {
                        "thumbnail": "http://books.google.com/books/clean_code.jpg"
                    },
                    "description": "<p>Even bad code can function.</p>",
                    "language": "en",
                },
            }
        ]
    }

    class MockHttp:
        def get_json(self, url, **kwargs):
            return fake_json

    gb.http = MockHttp()
    cands = gb.lookup_isbn("9780132350884")
    assert len(cands) == 1
    c = cands[0]
    assert c.title == "Clean Code"
    assert c.authors == ["Robert C. Martin"]
    assert c.year == 2008
    assert c.pages == 464
    assert c.isbn == "9780132350884"
    assert c.cover_url == "https://books.google.com/books/clean_code.jpg"  # switched to https
    assert c.description == "Even bad code can function."  # html stripped


# ── Scoring Tests ────────────────────────────────────────────────────────────

def test_scoring_candidate():
    local = {
        "title": "Design Patterns",
        "author": "Erich Gamma, Richard Helm",
        "year": 1994,
        "pages": 395,
        "isbn": "9780201633610",
    }

    # Exact ISBN match scores 1.0
    cand_exact_isbn = Candidate(
        provider="openlibrary",
        provider_id="1",
        title="Different Title",
        isbn="9780201633610",
    )
    assert score_candidate(local, cand_exact_isbn) == 1.0

    # Title & author match
    cand_match = Candidate(
        provider="googlebooks",
        provider_id="2",
        title="Design Patterns: Elements of Reusable Object-Oriented Software",
        authors=["Erich Gamma", "Richard Helm", "Ralph Johnson", "John Vlissides"],
        year=1994,
        pages=395,
    )
    score = score_candidate(local, cand_match)
    assert score >= 0.60

    # Decision logic
    cand_match.score = 0.95
    decision, _ = decide_candidates([cand_match])
    assert decision == "apply"

    cand_match.score = 0.75
    decision, _ = decide_candidates([cand_match])
    assert decision == "review"

    cand_match.score = 0.40
    decision, _ = decide_candidates([cand_match])
    assert decision == "not_found"


# ── Merge and History Undo Tests ──────────────────────────────────────────────

def test_genre_cleaning():
    raw = ["Computers / Programming / General", "Accessible book", "Protected DAISY", "Science Fiction / General"]
    cleaned = clean_genres(raw)
    assert "Accessible" not in cleaned
    assert "Daisy" not in cleaned
    assert "General" not in cleaned
    assert "Computers, Programming, Science Fiction" in cleaned


def test_merge_and_undo(tmp_path: Path):
    from booklib.db.database import Database
    db = Database(tmp_path / "test.db")
    conn = db.connect()


    # Insert folder and book
    conn.execute("INSERT INTO folders (id, path) VALUES (1, 'C:/')")
    conn.execute(
        """INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime,
                              title, author, publisher, field_sources)
           VALUES (1, 1, 'C:/test.pdf', 'test.pdf', 'pdf', 100, 1.0,
                   'Manual Title', NULL, 'File Pub', '{"title": "manual"}')"""
    )
    conn.commit()

    cand = Candidate(
        provider="openlibrary",
        provider_id="OL123",
        title="Online Title",  # Should NOT overwrite manual title!
        authors=["Online Author"],
        publisher="Online Publisher",
        year=2020,
    )

    batch_id = "test_batch_1"
    changed = apply_candidate(conn, 1, cand, batch_id=batch_id, mode="replace")

    # Title was manual, so only author, publisher, year should have changed
    assert "title" not in changed
    assert "author" in changed
    assert "publisher" in changed
    assert "year" in changed

    row = conn.execute("SELECT title, author, publisher, year, field_sources FROM books WHERE id = 1").fetchone()
    assert row[0] == "Manual Title"
    assert row[1] == "Online Author"
    assert row[2] == "Online Publisher"
    assert row[3] == 2020
    sources = json.loads(row[4])
    assert sources["title"] == "manual"
    assert sources["author"] == "online:openlibrary"

    # Now test undo
    undone = undo_batch(conn, batch_id)
    assert undone == 1

    row_after = conn.execute("SELECT title, author, publisher, year, field_sources FROM books WHERE id = 1").fetchone()
    assert row_after[0] == "Manual Title"
    assert row_after[1] is None
    assert row_after[2] == "File Pub"
    assert row_after[3] is None

    db.close()
