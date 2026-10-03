"""
test_v3_migration.py – Verify database migration from version 2 to version 3.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from booklib.db.database import Database, CURRENT_SCHEMA_VERSION


def _build_v2_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 2")
    conn.executescript(
        """
        CREATE TABLE folders (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_scanned_at TEXT
        );
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
            path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            format TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            file_mtime REAL NOT NULL,
            title TEXT,
            author TEXT,
            publisher TEXT,
            year INTEGER,
            isbn TEXT,
            pages INTEGER,
            genre TEXT,
            language TEXT,
            cover_path TEXT,
            date_added TEXT NOT NULL DEFAULT (datetime('now')),
            last_opened_at TEXT,
            open_count INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            status_changed_at TEXT,
            rating INTEGER,
            notes TEXT,
            edited_fields TEXT,
            is_missing INTEGER NOT NULL DEFAULT 0,
            file_hash TEXT
        );
        CREATE TABLE custom_readers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            exe_path TEXT NOT NULL,
            args_template TEXT NOT NULL DEFAULT '{file}',
            formats TEXT NOT NULL DEFAULT '*'
        );
        CREATE TABLE format_defaults (
            format TEXT PRIMARY KEY,
            reader_key TEXT NOT NULL
        );
        """
    )

    # Insert test folder and books
    conn.execute("INSERT INTO folders (id, path) VALUES (1, 'C:/Books')")
    conn.execute(
        """INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime,
                              title, author, status, status_changed_at, edited_fields)
           VALUES (1, 1, 'C:/Books/book1.pdf', 'book1.pdf', 'pdf', 1000, 12345.0,
                   'Custom Title', 'Custom Author', 'reading', '2025-05-10 14:00:00',
                   '["title", "author"]')"""
    )
    conn.execute(
        """INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime,
                              title, author, status, status_changed_at, edited_fields)
           VALUES (2, 1, 'C:/Books/book2.mobi', 'book2.mobi', 'mobi', 2000, 12345.0,
                   'Mobi Book', 'Some Author', 'read', '2025-06-01 10:00:00', NULL)"""
    )
    conn.commit()
    conn.close()


def test_v2_to_v3_migration(tmp_path: Path):
    db_file = tmp_path / "library.db"
    _build_v2_db(db_file)

    # Instantiate Database and connect which triggers migration
    db = Database(db_file)
    conn = db.connect()

    # Check schema version
    ver = conn.execute("PRAGMA user_version").fetchone()[0]

    assert ver == CURRENT_SCHEMA_VERSION

    # Check backup was created
    bak_file = tmp_path / "library.db.bak-v2"
    assert bak_file.exists()

    # Check field provenance conversion
    row1 = conn.execute("SELECT field_sources, cover_source FROM books WHERE id = 1").fetchone()
    fs1 = json.loads(row1[0])
    assert fs1 == {"title": "manual", "author": "manual"}
    assert row1[1] == "file"

    row2 = conn.execute("SELECT field_sources, cover_source FROM books WHERE id = 2").fetchone()
    assert row2[1] == "placeholder"

    # Check reading_log migration
    logs1 = conn.execute("SELECT started_on, finished_on FROM reading_log WHERE book_id = 1").fetchall()
    assert len(logs1) == 1
    assert logs1[0][0] == "2025-05-10"
    assert logs1[0][1] is None

    logs2 = conn.execute("SELECT started_on, finished_on FROM reading_log WHERE book_id = 2").fetchall()
    assert len(logs2) == 1
    assert logs2[0][1] == "2025-06-01"

    # Check new tables exist
    for tbl in ["series", "tags", "book_tags", "collections", "collection_books", "online_cache", "metadata_history", "duplicate_ignores"]:
        cnt = conn.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{tbl}'").fetchone()[0]
        assert cnt == 1, f"Table {tbl} not found"

    db.close()

    # Reopen to verify idempotency
    db2 = Database(db_file)
    conn2 = db2.connect()
    ver2 = conn2.execute("PRAGMA user_version").fetchone()[0]
    assert ver2 == CURRENT_SCHEMA_VERSION
    db2.close()
