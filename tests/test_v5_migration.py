"""
test_v5_migration.py – Verify database migration from v4 to v5.
"""
import sqlite3
from pathlib import Path

import pytest

from booklib.db.database import Database, CURRENT_SCHEMA_VERSION


def _build_v4_db(db_path: Path) -> None:
    """Create a minimal v4 database to test migration from."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 4")
    conn.executescript("""
        CREATE TABLE folders (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_scanned_at TEXT,
            watch INTEGER NOT NULL DEFAULT 0,
            auto_lookup INTEGER NOT NULL DEFAULT 0,
            kind TEXT NOT NULL DEFAULT 'local',
            source TEXT NOT NULL DEFAULT 'local',
            account_id INTEGER,
            drive_folder_id TEXT,
            drive_display TEXT,
            sync_token TEXT,
            include_subfolders INTEGER NOT NULL DEFAULT 1,
            deep_index INTEGER NOT NULL DEFAULT 0,
            sync_enabled INTEGER NOT NULL DEFAULT 1,
            sync_auto INTEGER NOT NULL DEFAULT 1
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
            is_missing INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            rating INTEGER,
            source TEXT NOT NULL DEFAULT 'local',
            drive_file_id TEXT,
            md5 TEXT,
            index_level TEXT NOT NULL DEFAULT 'full',
            keep_offline INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE reading_log (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            started_on TEXT,
            finished_on TEXT
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
        CREATE TABLE book_tags (
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (book_id, tag_id)
        );
        CREATE TABLE collections (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'manual',
            smart_query TEXT
        );
        CREATE TABLE collection_books (
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            PRIMARY KEY (collection_id, book_id)
        );
        CREATE TABLE metadata_history (
            id INTEGER PRIMARY KEY,
            book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
            source TEXT,
            before_json TEXT,
            after_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE drive_accounts (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE drive_folders (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES drive_accounts(id) ON DELETE CASCADE,
            folder_id TEXT NOT NULL,
            name TEXT,
            sync_token TEXT
        );
        CREATE TABLE cache_entries (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            local_path TEXT NOT NULL,
            size_bytes INTEGER,
            downloaded_at TEXT
        );
    """)
    conn.close()


@pytest.fixture
def v4_db(tmp_path):
    db_path = tmp_path / "library.db"
    _build_v4_db(db_path)
    return db_path


def test_migration_produces_correct_schema_version(v4_db):
    db = Database(v4_db)
    db.connect()
    ver = db.conn.execute("PRAGMA user_version").fetchone()[0]
    db.close()
    assert ver >= 5
    assert CURRENT_SCHEMA_VERSION >= 5


def test_new_tables_exist(v4_db):
    db = Database(v4_db)
    db.connect()
    tables = {
        r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    db.close()
    assert "conversion_log" in tables
    assert "rename_batches" in tables
    assert "rename_log" in tables
    assert "goals" in tables
    assert "temp_files" in tables


def test_converted_from_column_exists(v4_db):
    db = Database(v4_db)
    db.connect()
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(books)").fetchall()}
    db.close()
    assert "converted_from" in cols


def test_goals_unique_constraint(v4_db):
    db = Database(v4_db)
    db.connect()
    db.conn.execute("INSERT INTO goals (year, kind, target) VALUES (2026, 'books', 24)")
    db.conn.commit()
    import sqlite3 as sq
    with pytest.raises(sq.IntegrityError):
        db.conn.execute("INSERT INTO goals (year, kind, target) VALUES (2026, 'books', 30)")
        db.conn.commit()
    db.close()


def test_running_migration_twice_is_safe(v4_db):
    """Migration can run on an already-migrated DB without errors."""
    db = Database(v4_db)
    db.connect()
    db.close()
    # Open again — should not fail
    db2 = Database(v4_db)
    db2.connect()
    ver = db2.conn.execute("PRAGMA user_version").fetchone()[0]
    db2.close()
    assert ver >= 5


def test_existing_data_intact(v4_db):
    """Pre-existing data (books rows) survive the migration."""
    # Insert a book before migration
    raw = sqlite3.connect(str(v4_db))
    raw.execute("INSERT INTO folders (id, path) VALUES (1, '/books')")
    raw.execute(
        "INSERT INTO books (id, folder_id, path, filename, format, size_bytes, file_mtime) "
        "VALUES (1, 1, '/books/test.epub', 'test.epub', 'epub', 1000, 0.0)"
    )
    raw.commit()
    raw.close()

    db = Database(v4_db)
    db.connect()
    count = db.conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    db.close()
    assert count == 1
