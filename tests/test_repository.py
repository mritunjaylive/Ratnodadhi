"""
test_repository.py – unit tests for the Repository data-access layer.
"""
import sqlite3
from pathlib import Path

import pytest

from booklib.db.database import Database
from booklib.db.repository import Repository


@pytest.fixture()
def db_repo(tmp_path: Path):
    """Return a fresh (Repository, connection) pair backed by a temp DB."""
    db = Database(tmp_path / "test.db")
    conn = db.connect()
    repo = Repository(conn)
    return repo, conn


def _add_folder(repo: Repository, path: str = "/tmp/lib") -> int:
    return repo.add_folder(path)


def _upsert(repo: Repository, folder_id: int, path: str = "/tmp/lib/book.pdf",
            **kwargs) -> int:
    defaults = dict(
        folder_id=folder_id,
        path=path,
        filename="book.pdf",
        format="pdf",
        size_bytes=1024,
        file_mtime=1000.0,
        title="Test Book",
        author="Test Author",
        publisher=None,
        year=2020,
        isbn=None,
        pages=100,
        genre=None,
        language=None,
        cover_path=None,
    )
    defaults.update(kwargs)
    return repo.upsert_book(**defaults)


def test_add_folder(db_repo):
    repo, _ = db_repo
    fid = _add_folder(repo)
    assert fid > 0
    folders = repo.list_folders()
    assert len(folders) == 1
    assert folders[0]["path"] == "/tmp/lib"


def test_upsert_no_duplicate(db_repo):
    repo, conn = db_repo
    fid = _add_folder(repo)
    id1 = _upsert(repo, fid)
    id2 = _upsert(repo, fid)   # same path, second call
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    assert count == 1           # no duplicate
    assert id1 == id2           # same id returned


def test_upsert_updates_changed_file(db_repo):
    repo, conn = db_repo
    fid = _add_folder(repo)
    _upsert(repo, fid, title="Old Title")
    _upsert(repo, fid, title="New Title")
    conn.commit()
    book = repo.get_book_by_path("/tmp/lib/book.pdf")
    assert book["title"] == "New Title"


def test_mark_missing(db_repo):
    repo, conn = db_repo
    fid = _add_folder(repo)
    _upsert(repo, fid)
    conn.commit()
    repo.mark_missing(["/tmp/lib/book.pdf"])
    conn.commit()
    book = repo.get_book_by_path("/tmp/lib/book.pdf")
    assert book["is_missing"] == 1


def test_remove_missing(db_repo):
    repo, conn = db_repo
    fid = _add_folder(repo)
    _upsert(repo, fid)
    conn.commit()
    repo.mark_missing(["/tmp/lib/book.pdf"])
    conn.commit()
    removed = repo.remove_missing()
    assert removed == 1
    count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    assert count == 0


def test_list_books_sorted(db_repo):
    repo, conn = db_repo
    fid = _add_folder(repo)
    _upsert(repo, fid, path="/tmp/lib/b.pdf", title="Zephyr")
    _upsert(repo, fid, path="/tmp/lib/a.pdf", title="Alpha")
    conn.commit()
    books = repo.list_books(sort_field="title", ascending=True)
    titles = [b.title for b in books]
    assert titles == ["Alpha", "Zephyr"]


def test_remove_folder_cascades(db_repo):
    repo, conn = db_repo
    fid = _add_folder(repo)
    _upsert(repo, fid)
    conn.commit()
    repo.remove_folder(fid)
    count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    assert count == 0
