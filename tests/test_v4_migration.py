"""
test_v4_migration.py – Verify database migration from version 3 to version 4.
"""
import sqlite3
from pathlib import Path

import pytest

from booklib.db.database import Database, CURRENT_SCHEMA_VERSION


def _build_v3_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 3")
    conn.executescript(
        """
        CREATE TABLE folders (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_scanned_at TEXT,
            watch INTEGER NOT NULL DEFAULT 0,
            auto_lookup INTEGER NOT NULL DEFAULT 0
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
            field_sources TEXT,
            cover_source TEXT DEFAULT 'file',
            is_missing INTEGER NOT NULL DEFAULT 0,
            file_hash TEXT,
            quick_hash TEXT,
            description TEXT,
            online_source TEXT,
            online_id TEXT,
            lookup_status TEXT,
            lookup_at TEXT,
            series_id INTEGER,
            series_index REAL,
            progress_page INTEGER,
            progress_percent REAL,
            tags_text TEXT,
            source TEXT NOT NULL DEFAULT 'local',
            drive_file_id TEXT
        );
        CREATE TABLE series (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE
        );
        CREATE TABLE book_tags (
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (book_id, tag_id)
        );
        CREATE TABLE collections (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'manual',
            query_json TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE collection_books (
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (collection_id, book_id)
        );
        CREATE TABLE reading_log (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            started_on TEXT,
            finished_on TEXT
        );
        CREATE TABLE metadata_history (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            applied_at TEXT NOT NULL DEFAULT (datetime('now')),
            source TEXT NOT NULL,
            old_snapshot TEXT NOT NULL,
            batch_id TEXT
        );
        CREATE TABLE online_cache (
            key TEXT PRIMARY KEY,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL,
            response_json TEXT NOT NULL
        );
        CREATE TABLE duplicate_ignores (
            book_id_a INTEGER NOT NULL,
            book_id_b INTEGER NOT NULL,
            ignored_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (book_id_a, book_id_b)
        );
        """
    )

    # Insert test folder and books
    conn.execute("INSERT INTO folders (id, path) VALUES (1, 'C:/Books')")
    conn.execute(
        """INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime,
                              title, author, status)
           VALUES (1, 1, 'C:/Books/book1.pdf', 'book1.pdf', 'pdf', 1000, 12345.0,
                   'Book 1', 'Author 1', 'reading')"""
    )
    conn.commit()
    conn.close()


def test_v3_to_v4_migration(tmp_path: Path):
    db_file = tmp_path / "library.db"
    _build_v3_db(db_file)

    # Connect triggers migration to version 4
    db = Database(db_file)
    conn = db.connect()

    # Check schema version
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver == CURRENT_SCHEMA_VERSION

    # Check backup file was created
    bak_file = tmp_path / "library.db.bak-v3"
    assert bak_file.exists()

    # Check existing local book is preserved with default source = 'local'
    row1 = conn.execute(
        "SELECT id, path, source, drive_file_id, keep_offline FROM books WHERE id = 1"
    ).fetchone()
    assert row1["id"] == 1
    assert row1["path"] == "C:/Books/book1.pdf"
    assert row1["source"] == "local"
    assert row1["drive_file_id"] is None
    assert row1["keep_offline"] == 0

    # Check new tables exist
    for tbl in ["drive_accounts", "drive_nodes", "drive_cache", "app_meta"]:
        cnt = conn.execute(
            f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{tbl}'"
        ).fetchone()[0]
        assert cnt == 1, f"Table {tbl} not found"

    # Check new columns on folders table
    f_cols = [c["name"] for c in conn.execute("PRAGMA table_info(folders)").fetchall()]
    assert "source" in f_cols
    assert "account_id" in f_cols
    assert "drive_folder_id" in f_cols
    assert "sync_token" in f_cols
    assert "include_subfolders" in f_cols
    assert "sync_auto" in f_cols

    # Check new columns on books table
    b_cols = [c["name"] for c in conn.execute("PRAGMA table_info(books)").fetchall()]
    assert "source" in b_cols
    assert "drive_file_id" in b_cols
    assert "md5" in b_cols
    assert "drive_path" in b_cols
    assert "drive_web_link" in b_cols
    assert "index_level" in b_cols
    assert "keep_offline" in b_cols

    db.close()

    # Verify idempotency by opening again
    db2 = Database(db_file)
    conn2 = db2.connect()
    ver2 = conn2.execute("PRAGMA user_version").fetchone()[0]
    assert ver2 == CURRENT_SCHEMA_VERSION
    db2.close()
