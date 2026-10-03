"""
test_v2_status_and_edits.py – Tests for reading status, ratings, notes, and metadata editing with rescan protection.
"""
from pathlib import Path

import pytest

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.metadata.filename import validate_isbn


@pytest.fixture()
def repo_with_book(tmp_path: Path):
    db = Database(tmp_path / "status_test.db")
    conn = db.connect()
    repo = Repository(conn)
    fid = repo.add_folder("/library")
    bid = repo.upsert_book(
        folder_id=fid,
        path="/library/clean_code.pdf",
        filename="clean_code.pdf",
        format="pdf",
        size_bytes=2048,
        file_mtime=100.0,
        title="Clean Code",
        author="Robert Martin",
        publisher="Prentice Hall",
        year=2008,
        isbn="9780132350884",
        pages=464,
        genre="Programming",
        language="English",
        cover_path=None,
    )
    yield repo, bid, fid
    db.close()


def test_status_transitions_and_validation(repo_with_book):
    repo, bid, _ = repo_with_book

    # Initially unset
    d = repo.get_book_detail(bid)
    assert d.status is None

    # Set to 'want'
    repo.set_status([bid], "want")
    d = repo.get_book_detail(bid)
    assert d.status == "want"

    # Set to 'reading'
    repo.set_status([bid], "reading")
    d = repo.get_book_detail(bid)
    assert d.status == "reading"

    # Set to 'read'
    repo.set_status([bid], "read")
    d = repo.get_book_detail(bid)
    assert d.status == "read"

    # Clear status
    repo.set_status([bid], None)
    d = repo.get_book_detail(bid)
    assert d.status is None

    # Invalid status raises ValueError
    with pytest.raises(ValueError):
        repo.set_status([bid], "finished")


def test_rating_and_notes(repo_with_book):
    repo, bid, _ = repo_with_book

    repo.set_rating(bid, 5)
    d = repo.get_book_detail(bid)
    assert d.rating == 5

    repo.set_rating(bid, None)
    d = repo.get_book_detail(bid)
    assert d.rating is None

    with pytest.raises(ValueError):
        repo.set_rating(bid, 6)

    with pytest.raises(ValueError):
        repo.set_rating(bid, 0)

    # Notes
    repo.set_notes(bid, "Must re-read chapter 3")
    d = repo.get_book_detail(bid)
    assert d.notes == "Must re-read chapter 3"


def test_record_open(repo_with_book):
    repo, bid, _ = repo_with_book
    d = repo.get_book_detail(bid)
    assert d.open_count == 0
    assert d.last_opened_at is None

    repo.record_open(bid)
    d2 = repo.get_book_detail(bid)
    assert d2.open_count == 1
    assert d2.last_opened_at is not None

    repo.record_open(bid)
    d3 = repo.get_book_detail(bid)
    assert d3.open_count == 2


def test_rescan_protection_for_edited_fields(repo_with_book):
    repo, bid, fid = repo_with_book

    # Edit the title manually
    repo.edit_book(bid, {"title": "Clean Code: A Handbook of Agile Software Craftsmanship"})

    d = repo.get_book_detail(bid)
    assert d.title == "Clean Code: A Handbook of Agile Software Craftsmanship"
    assert "title" in d.edited_fields

    # Simulate rescan with original file title, but changed file size and new year
    bid_after = repo.upsert_book(
        folder_id=fid,
        path="/library/clean_code.pdf",
        filename="clean_code.pdf",
        format="pdf",
        size_bytes=4096,  # updated file size
        file_mtime=200.0,
        title="Clean Code",  # original file title
        author="Robert Martin",
        publisher="Prentice Hall",
        year=2009,  # unedited metadata field
        isbn="9780132350884",
        pages=464,
        genre="Programming",
        language="English",
        cover_path=None,
    )
    assert bid_after == bid

    # Assert: edited title is preserved! But size_bytes and year updated!
    d_after = repo.get_book_detail(bid)
    assert d_after.title == "Clean Code: A Handbook of Agile Software Craftsmanship"
    assert d_after.size_bytes == 4096
    assert d_after.year == 2009


def test_revert_metadata(repo_with_book):
    repo, bid, _ = repo_with_book

    # Edit multiple fields
    repo.edit_book(bid, {"title": "Custom Title", "author": "Custom Author"})
    d = repo.get_book_detail(bid)
    assert d.title == "Custom Title"
    assert "title" in d.edited_fields
    assert "author" in d.edited_fields

    # Revert to file metadata
    repo.revert_book(bid, {
        "title": "Clean Code",
        "author": "Robert Martin",
        "publisher": "Prentice Hall",
        "year": 2008,
        "isbn": "9780132350884",
        "pages": 464,
        "genre": "Programming",
        "language": "English",
    })

    d_rev = repo.get_book_detail(bid)
    assert d_rev.title == "Clean Code"
    assert d_rev.author == "Robert Martin"
    assert len(d_rev.edited_fields) == 0


def test_bulk_edit(repo_with_book):
    repo, bid1, fid = repo_with_book
    bid2 = repo.upsert_book(
        folder_id=fid,
        path="/library/refactoring.pdf",
        filename="refactoring.pdf",
        format="pdf",
        size_bytes=1024,
        file_mtime=1.0,
        title="Refactoring",
        author="Martin Fowler",
        publisher="Addison-Wesley",
        year=1999,
        isbn=None,
        pages=431,
        genre="CS",
        language="English",
        cover_path=None,
    )

    repo.bulk_edit_books([bid1, bid2], {"genre": "Software Engineering", "year": 2021})

    d1 = repo.get_book_detail(bid1)
    d2 = repo.get_book_detail(bid2)
    assert d1.genre == "Software Engineering"
    assert d2.genre == "Software Engineering"
    assert d1.year == 2021
    assert d2.year == 2021
    assert "genre" in d1.edited_fields
    assert "year" in d2.edited_fields


def test_isbn_validation():
    # Valid ISBN-10
    assert validate_isbn("0-306-40615-2") == "0306406152"
    # Valid ISBN-13
    assert validate_isbn("978-0-306-40615-7") == "9780306406157"
    # Invalid ISBN
    assert validate_isbn("1234567890") is None
    assert validate_isbn("invalid") is None
