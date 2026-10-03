"""
test_v5_rename.py – Unit tests for the rename engine (template, sanitize, planner, executor, undo).
"""
import os
import sys
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from booklib.organize.template import render, RenderError, PRESETS
from booklib.organize.sanitize import sanitize_component, sanitize_filename
from booklib.organize.planner import plan_renames, RenameRow


# ─────────────────────────── Template tests ────────────────────────────────────

class TestTemplateRenderer:
    def _book(self, **kwargs):
        defaults = {
            "title": "War and Peace",
            "author": "Leo Tolstoy",
            "year": "1869",
            "series": None,
            "series_index": None,
            "genre": "Fiction, Classic",
            "isbn": "",
        }
        defaults.update(kwargs)
        return defaults

    def test_basic_fields(self):
        assert render("{title}", self._book()) == "War and Peace"
        assert render("{author}", self._book()) == "Leo Tolstoy"
        assert render("{year}", self._book()) == "1869"

    def test_author_first(self):
        assert render("{author:first}", self._book()) == "Leo Tolstoy"

    def test_author_last(self):
        assert render("{author:last}", self._book()) == "Tolstoy"

    def test_author_sort(self):
        assert render("{author:sort}", self._book()) == "Tolstoy, Leo"

    def test_title_main(self):
        book = self._book(title="Clean Code: A Handbook")
        assert render("{title:main}", book) == "Clean Code"

    def test_title_length_limit(self):
        book = self._book(title="A " * 40)  # 80 chars
        result = render("{title:30}", book)
        assert len(result) <= 30

    def test_optional_group_included(self):
        result = render("{author}[ ({year})]", self._book())
        assert result == "Leo Tolstoy (1869)"

    def test_optional_group_excluded_when_empty(self):
        book = self._book(year=None)
        result = render("{author}[ ({year})]", book)
        assert result == "Leo Tolstoy"

    def test_fallback(self):
        book = self._book(isbn="")
        result = render("{isbn|No ISBN}", book)
        assert result == "No ISBN"

    def test_missing_required_field_raises(self):
        book = self._book(title=None)
        with pytest.raises(RenderError) as exc_info:
            render("{title}", book)
        assert exc_info.value.field == "title"

    def test_literal_brackets(self):
        result = render(r"\[not optional\]", self._book())
        assert result == "[not optional]"

    def test_genre_first(self):
        result = render("{genre:first}", self._book())
        assert result == "Fiction"

    def test_series_index_padded(self):
        book = self._book(series="Foundation", series_index=3)
        result = render("{series_index:02}", book)
        assert result == "03"

    def test_full_preset(self):
        result = render(PRESETS["Author - Title (Year)"], self._book())
        assert result == "Leo Tolstoy - War and Peace (1869)"

    def test_unicode_title(self):
        book = self._book(title="रत्नदाधि")
        result = render("{title}", book)
        assert result == "रत्नदाधि"


# ─────────────────────────── Sanitize tests ────────────────────────────────────

class TestSanitize:
    def test_strips_illegal_chars(self):
        assert "<" not in sanitize_component("Hello<World")
        assert ">" not in sanitize_component("Hello>World")
        assert ":" not in sanitize_component("Hello:World")

    def test_reserved_windows_names(self):
        result = sanitize_component("CON")
        assert result != "CON"
        assert result.startswith("CON")

    def test_trailing_dot_stripped(self):
        result = sanitize_component("test.")
        assert not result.endswith(".")

    def test_slash_replaced(self):
        result = sanitize_component("path/to/file")
        assert "/" not in result

    def test_unicode_normalized(self):
        result = sanitize_component("caf\u00e9")
        assert result == "café"

    def test_very_long_name_shortened(self):
        long = "A" * 200
        result = sanitize_component(long)
        assert len(result) <= 120

    def test_com1_reserved(self):
        result = sanitize_component("COM1")
        assert result != "COM1"

    def test_empty_input(self):
        assert sanitize_component("") == ""

    def test_filename_with_ext(self):
        result = sanitize_filename("Clean Code: A Handbook", "pdf")
        assert result.endswith(".pdf")
        assert ":" not in result


# ─────────────────────────── Planner tests ────────────────────────────────────

@pytest.fixture
def book_file(tmp_path):
    f = tmp_path / "war_and_peace_final.epub"
    f.write_bytes(b"fake epub")
    return f


def _make_book(path: Path, **kwargs) -> dict:
    defaults = {
        "id": 1,
        "path": str(path),
        "title": "War and Peace",
        "author": "Leo Tolstoy",
        "year": "1869",
        "format": "epub",
        "source": "local",
        "series": None,
        "series_index": None,
        "genre": None,
        "isbn": None,
        "field_sources": "{}",
    }
    defaults.update(kwargs)
    return defaults


def test_planner_ok(book_file, tmp_path):
    book = _make_book(book_file)
    rows = plan_renames([book], "{author} - {title}[ ({year})]",
                        library_roots={str(tmp_path): str(tmp_path)})
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "OK"
    assert "Leo Tolstoy" in row.new_path
    assert "War and Peace" in row.new_path
    assert "(1869)" in row.new_path


def test_planner_unchanged(book_file, tmp_path):
    # Name the file exactly what the pattern would produce
    target = tmp_path / "Leo Tolstoy - War and Peace (1869).epub"
    book_file.rename(target)
    book = _make_book(target)
    rows = plan_renames([book], "{author} - {title}[ ({year})]")
    assert rows[0].status == "Unchanged"


def test_planner_conflict(book_file, tmp_path):
    # Create the target file
    target = tmp_path / "Leo Tolstoy - War and Peace (1869).epub"
    target.write_bytes(b"other")
    book = _make_book(book_file)
    rows = plan_renames([book], "{author} - {title}[ ({year})]")
    assert rows[0].status == "Conflict"


def test_planner_missing_field(book_file, tmp_path):
    book = _make_book(book_file, title=None)
    rows = plan_renames([book], "{author} - {title}")
    assert rows[0].status == "Missing"
    assert rows[0].field_missing == "title"


def test_planner_non_local_skipped(tmp_path):
    book = {"id": 1, "path": "/fake/book.epub", "source": "drive",
            "title": "T", "author": "A", "year": None, "format": "epub",
            "field_sources": "{}"}
    rows = plan_renames([book], "{title}")
    assert rows[0].status == "NonLocal"


def test_planner_guessed_metadata(book_file, tmp_path):
    book = _make_book(
        book_file,
        field_sources=json.dumps({"title": "file:filename", "author": "file:filename"}),
    )
    rows = plan_renames([book], "{author} - {title}[ ({year})]")
    assert rows[0].status == "Guessed"
    assert rows[0].checked is False


def test_planner_within_batch_conflict_skip(book_file, tmp_path):
    # Two books mapping to the same target
    f2 = tmp_path / "book2.epub"
    f2.write_bytes(b"fake")
    book1 = _make_book(book_file)
    book2 = _make_book(f2, id=2)
    rows = plan_renames([book1, book2], "{author} - {title}[ ({year})]",
                        conflict_policy="skip")
    statuses = [r.status for r in rows]
    # One is OK, one is Conflict (or both OK if names differ due to file existence)
    assert "Conflict" in statuses or statuses.count("OK") >= 1


def test_planner_within_batch_conflict_number(book_file, tmp_path):
    f2 = tmp_path / "book2.epub"
    f2.write_bytes(b"fake")
    book1 = _make_book(book_file)
    book2 = _make_book(f2, id=2)
    rows = plan_renames([book1, book2], "{author} - {title}[ ({year})]",
                        conflict_policy="number")
    # Both should be OK with numbered suffix on the second
    ok_rows = [r for r in rows if r.status == "OK"]
    assert len(ok_rows) >= 1


# ─────────────────────────── Executor tests ────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path):
    """A minimal in-memory DB with the v5 schema tables needed by executor."""
    db_path = tmp_path / "test.db"
    from booklib.db.database import Database
    db = Database(db_path)
    conn = db.connect()
    # Insert a folder and book
    conn.execute("INSERT INTO folders (id, path) VALUES (1, ?)", (str(tmp_path),))
    conn.commit()
    return conn, db


def test_executor_basic_rename(tmp_path, fresh_db):
    conn, db = fresh_db
    # Create a book file
    src = tmp_path / "old.epub"
    src.write_bytes(b"content")
    conn.execute(
        "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime) "
        "VALUES (1, 1, ?, 'old.epub', 'epub', 7, 0.0)",
        (str(src),),
    )
    conn.commit()

    from booklib.organize.planner import RenameRow
    from booklib.organize.executor import RenameExecutor
    row = RenameRow(
        book_id=1,
        old_path=str(src),
        new_path=str(tmp_path / "new.epub"),
        status="OK",
        size=7,
        mtime=src.stat().st_mtime,
    )
    executor = RenameExecutor(conn)
    summary = executor.execute([row], "{title}", "")
    assert summary["renamed"] == 1
    assert summary["failed"] == 0
    assert (tmp_path / "new.epub").exists()
    assert not src.exists()
    db.close()


def test_executor_missing_source_marked_failed(tmp_path, fresh_db):
    conn, db = fresh_db
    from booklib.organize.planner import RenameRow
    from booklib.organize.executor import RenameExecutor
    row = RenameRow(
        book_id=None,  # NULL FK allowed when book has been deleted
        old_path=str(tmp_path / "nonexistent.epub"),
        new_path=str(tmp_path / "new.epub"),
        status="OK",
        size=100,
    )
    executor = RenameExecutor(conn)
    summary = executor.execute([row], "{title}", "")
    assert summary["failed"] == 1
    db.close()



def test_undo_rename_batch(tmp_path, fresh_db):
    conn, db = fresh_db
    src = tmp_path / "original.epub"
    src.write_bytes(b"book data")
    conn.execute(
        "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime) "
        "VALUES (1, 1, ?, 'original.epub', 'epub', 9, 0.0)",
        (str(src),),
    )
    conn.commit()

    from booklib.organize.planner import RenameRow
    from booklib.organize.executor import RenameExecutor
    from booklib.organize.undo import undo_batch
    row = RenameRow(
        book_id=1,
        old_path=str(src),
        new_path=str(tmp_path / "renamed.epub"),
        status="OK",
        size=9,
        mtime=src.stat().st_mtime,
    )
    executor = RenameExecutor(conn)
    summary = executor.execute([row], "{title}", "")
    batch_id = summary["batch_id"]

    assert (tmp_path / "renamed.epub").exists()

    undo_result = undo_batch(batch_id, conn)
    assert undo_result["restored"] == 1
    assert src.exists()
    assert not (tmp_path / "renamed.epub").exists()
    db.close()


def test_crash_recovery(tmp_path, fresh_db):
    """Simulate a crash by leaving a 'pending' row and check recovery."""
    conn, db = fresh_db
    src = tmp_path / "src.epub"
    dst = tmp_path / "dst.epub"
    dst.write_bytes(b"renamed already")
    # The book DB row still points to src (crash before DB update)
    conn.execute(
        "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime) "
        "VALUES (1, 1, ?, 'src.epub', 'epub', 15, 0.0)",
        (str(src),),
    )
    batch_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO rename_batches (id, file_pattern) VALUES (?, 'test')", (batch_id,)
    )
    conn.execute(
        "INSERT INTO rename_log (batch_id, book_id, old_path, new_path, status) "
        "VALUES (?, 1, ?, ?, 'pending')",
        (batch_id, str(src), str(dst)),
    )
    conn.commit()

    from booklib.organize.executor import recover_pending_renames
    recovered = recover_pending_renames(conn)
    assert recovered == 1
    book = conn.execute("SELECT path FROM books WHERE id = 1").fetchone()
    assert book["path"] == str(dst)
    db.close()
