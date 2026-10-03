-- schema.sql -- SQLite schema for BookLib.
--
-- Version history (stored in PRAGMA user_version):
--   1 - initial v1 schema (folders + books)

CREATE TABLE IF NOT EXISTS folders (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL UNIQUE,
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    last_scanned_at TEXT
);

CREATE TABLE IF NOT EXISTS books (
    id            INTEGER PRIMARY KEY,
    folder_id     INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    path          TEXT NOT NULL UNIQUE,          -- absolute path
    filename      TEXT NOT NULL,
    format        TEXT NOT NULL,                 -- 'pdf', 'epub', etc.
    size_bytes    INTEGER NOT NULL,
    file_mtime    REAL NOT NULL,                 -- for change detection

    title         TEXT,
    author        TEXT,
    publisher     TEXT,
    year          INTEGER,
    edition       TEXT,
    isbn          TEXT,
    pages         INTEGER,
    genre         TEXT,
    language      TEXT,

    cover_path    TEXT,                          -- relative to covers dir
    is_missing    INTEGER NOT NULL DEFAULT 0,
    date_added    TEXT NOT NULL DEFAULT (datetime('now')),

    -- reserved for later versions (unused in v1)
    status        TEXT,                          -- v2: want / reading / read
    rating        INTEGER,                       -- v2
    notes         TEXT,                          -- v2
    metadata_src  TEXT DEFAULT 'file',           -- v3: file / online / manual
    file_hash     TEXT,                          -- v3: duplicate detection
    source        TEXT NOT NULL DEFAULT 'local', -- v4: local / drive
    drive_file_id TEXT                           -- v4
);

CREATE INDEX IF NOT EXISTS idx_books_title   ON books(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_books_author  ON books(author COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_books_folder  ON books(folder_id);
CREATE INDEX IF NOT EXISTS idx_books_missing ON books(is_missing);
