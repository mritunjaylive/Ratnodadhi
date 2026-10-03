"""
test_v2_undo.py – Tests for QUndoCommand subclasses (status, rating, metadata).
"""
from pathlib import Path

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from booklib.db.database import Database
from booklib.db.repository import Repository
from booklib.ui.commands import EditMetadataCommand, SetRatingCommand, SetStatusCommand


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


@pytest.fixture()
def repo_for_undo(tmp_path: Path):
    db = Database(tmp_path / "undo_test.db")
    conn = db.connect()
    repo = Repository(conn)
    fid = repo.add_folder("/books")
    bid1 = repo.upsert_book(
        folder_id=fid, path="/books/1.pdf", filename="1.pdf", format="pdf",
        size_bytes=1000, file_mtime=1.0, title="Title 1", author="Author 1",
        publisher=None, year=2000, isbn=None, pages=100, genre="Genre 1",
        language="en", cover_path=None,
    )
    bid2 = repo.upsert_book(
        folder_id=fid, path="/books/2.pdf", filename="2.pdf", format="pdf",
        size_bytes=1000, file_mtime=1.0, title="Title 2", author="Author 2",
        publisher=None, year=2000, isbn=None, pages=100, genre="Genre 2",
        language="en", cover_path=None,
    )
    yield repo, bid1, bid2
    db.close()


def test_status_undo_redo(qapp, repo_for_undo):
    repo, bid1, bid2 = repo_for_undo
    stack = QUndoStack()

    cmd = SetStatusCommand(
        repo=repo,
        book_ids=[bid1, bid2],
        new_status="reading",
        old_statuses={bid1: None, bid2: None},
    )
    stack.push(cmd)

    # Redo was applied
    assert repo.get_book_detail(bid1).status == "reading"
    assert repo.get_book_detail(bid2).status == "reading"

    # Undo
    stack.undo()
    assert repo.get_book_detail(bid1).status is None
    assert repo.get_book_detail(bid2).status is None

    # Redo
    stack.redo()
    assert repo.get_book_detail(bid1).status == "reading"
    assert repo.get_book_detail(bid2).status == "reading"


def test_rating_undo_redo(qapp, repo_for_undo):
    repo, bid1, _ = repo_for_undo
    stack = QUndoStack()

    cmd = SetRatingCommand(
        repo=repo,
        book_id=bid1,
        new_rating=5,
        old_rating=None,
    )
    stack.push(cmd)

    assert repo.get_book_detail(bid1).rating == 5

    stack.undo()
    assert repo.get_book_detail(bid1).rating is None

    stack.redo()
    assert repo.get_book_detail(bid1).rating == 5


def test_metadata_edit_undo_redo(qapp, repo_for_undo):
    repo, bid1, _ = repo_for_undo
    stack = QUndoStack()

    cmd = EditMetadataCommand(
        repo=repo,
        book_ids=[bid1],
        new_fields={"title": "Updated Title", "author": "New Author"},
        old_snapshots={bid1: {"title": "Title 1", "author": "Author 1"}},
    )
    stack.push(cmd)

    d = repo.get_book_detail(bid1)
    assert d.title == "Updated Title"
    assert d.author == "New Author"

    stack.undo()
    d_undone = repo.get_book_detail(bid1)
    assert d_undone.title == "Title 1"
    assert d_undone.author == "Author 1"

    stack.redo()
    d_redone = repo.get_book_detail(bid1)
    assert d_redone.title == "Updated Title"
    assert d_redone.author == "New Author"
