"""
test_v2_migration.py – Tests for Migration 2 from v1 schema.
"""
import sqlite3
from pathlib import Path

import pytest

from booklib.db.database import Database, CURRENT_SCHEMA_VERSION, fts5_available
from booklib.db.repository import Repository
from booklib.db.query import LibraryQuery


def test_v1_to_v2_migration(tmp_path: Path):
    db_file = tmp_path / "migration_test.db"

    # Step 1: Create a v1 database manually using schema.sql and set user_version = 1
    conn = sqlite3.connect(str(db_file))
    schema_sql = (Path(__file__).parent.parent / "booklib" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.execute("PRAGMA user_version = 1")

    # Insert sample v1 data
    conn.execute("INSERT INTO folders (path) VALUES ('/books')")
    fid = conn.execute("SELECT id FROM folders WHERE path = '/books'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO books (folder_id, path, filename, format, size_bytes, file_mtime, title, author, year)
        VALUES (?, '/books/war_and_peace.pdf', 'war_and_peace.pdf', 'pdf', 5000000, 1234567.0, 'War and Peace', 'Leo Tolstoy', 1869)
        """,
        (fid,)
    )
    conn.commit()
    conn.close()

    # Step 2: Open with Database class to trigger automatic migration to v2
    db = Database(db_file)
    conn2 = db.connect()

    # Verify user_version is migrated (at least 2, currently CURRENT_SCHEMA_VERSION)
    ver = conn2.execute("PRAGMA user_version").fetchone()[0]
    assert ver == CURRENT_SCHEMA_VERSION

    # Verify backup file was created
    bak_file = db_file.with_suffix(".db.bak-v1")
    assert bak_file.exists()

    # Verify v1 data is preserved
    row = conn2.execute("SELECT title, author, open_count, edited_fields FROM books WHERE id = 1").fetchone()
    assert row["title"] == "War and Peace"
    assert row["author"] == "Leo Tolstoy"
    assert row["open_count"] == 0

    # Verify FTS indexed existing books
    if fts5_available():
        fts_rows = conn2.execute("SELECT rowid FROM books_fts WHERE books_fts MATCH '\"Tolstoy\"*'").fetchall()
        assert len(fts_rows) == 1
        assert fts_rows[0][0] == 1

    # Running migration again is idempotent and safe
    db._migrate_v2()
    ver_again = conn2.execute("PRAGMA user_version").fetchone()[0]
    assert ver_again == CURRENT_SCHEMA_VERSION

    db.close()

