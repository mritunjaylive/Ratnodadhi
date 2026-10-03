-- migration_3.sql – Schema additions for v3 (Metadata Enrichment and Organization)
--
-- Executed by database.py _migrate_v3().
-- Note: ALTER TABLE statements are executed in Python with try/except.
-- This script creates the new tables, indices, and updated FTS5 virtual table with tags_text.

-- Indices
CREATE INDEX IF NOT EXISTS idx_books_size        ON books(size_bytes);
CREATE INDEX IF NOT EXISTS idx_books_quick_hash  ON books(quick_hash);
CREATE INDEX IF NOT EXISTS idx_books_file_hash   ON books(file_hash);
CREATE INDEX IF NOT EXISTS idx_books_isbn        ON books(isbn);
CREATE INDEX IF NOT EXISTS idx_books_series      ON books(series_id, series_index);
CREATE INDEX IF NOT EXISTS idx_books_lookup      ON books(lookup_status);

-- Series
CREATE TABLE IF NOT EXISTS series (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- Tags
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color TEXT
);

CREATE TABLE IF NOT EXISTS book_tags (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (book_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_book_tags_tag ON book_tags(tag_id);

-- Collections
CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind        TEXT NOT NULL DEFAULT 'manual',     -- 'manual' | 'smart'
    smart_query TEXT,                               -- JSON of a LibraryQuery (smart only)
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS collection_books (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    book_id       INTEGER NOT NULL REFERENCES books(id)       ON DELETE CASCADE,
    added_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, book_id)
);
CREATE INDEX IF NOT EXISTS idx_col_books_book ON collection_books(book_id);

-- Reading log (history of readings per book)
CREATE TABLE IF NOT EXISTS reading_log (
    id          INTEGER PRIMARY KEY,
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    started_on  TEXT,            -- ISO date 'YYYY-MM-DD', may be NULL
    finished_on TEXT,            -- ISO date 'YYYY-MM-DD', NULL while still reading
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_reading_log_book ON reading_log(book_id);

-- Online lookup caching
CREATE TABLE IF NOT EXISTS online_cache (
    cache_key  TEXT PRIMARY KEY,     -- e.g. 'openlibrary:isbn:978...' or 'cand:<book_id>'
    provider   TEXT NOT NULL,
    response   TEXT NOT NULL,        -- JSON string
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Change history for safe batch undo
CREATE TABLE IF NOT EXISTS metadata_history (
    id          INTEGER PRIMARY KEY,
    batch_id    TEXT NOT NULL,        -- UUID or timestamp batch ID
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,        -- e.g. 'online:openlibrary'
    before_json TEXT NOT NULL,       -- JSON snapshot of fields before change
    after_json  TEXT NOT NULL,       -- JSON snapshot of fields after change
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_meta_history_batch ON metadata_history(batch_id);

-- Dismissed duplicate groups
CREATE TABLE IF NOT EXISTS duplicate_ignores (
    group_key  TEXT PRIMARY KEY,     -- '<level>:<sorted_book_ids>'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Rebuild FTS with tags_text
DROP TRIGGER IF EXISTS books_ai;
DROP TRIGGER IF EXISTS books_ad;
DROP TRIGGER IF EXISTS books_au;
DROP TABLE IF EXISTS books_fts;

CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
    title, author, publisher, genre, isbn, notes, filename, tags_text,
    content='books', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
  INSERT INTO books_fts(rowid,title,author,publisher,genre,isbn,notes,filename,tags_text)
  VALUES (new.id,new.title,new.author,new.publisher,new.genre,new.isbn,new.notes,new.filename,new.tags_text);
END;

CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
  INSERT INTO books_fts(books_fts,rowid,title,author,publisher,genre,isbn,notes,filename,tags_text)
  VALUES ('delete',old.id,old.title,old.author,old.publisher,old.genre,old.isbn,old.notes,old.filename,old.tags_text);
END;

CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE OF title,author,publisher,genre,isbn,notes,filename,tags_text ON books BEGIN
  INSERT INTO books_fts(books_fts,rowid,title,author,publisher,genre,isbn,notes,filename,tags_text)
  VALUES ('delete',old.id,old.title,old.author,old.publisher,old.genre,old.isbn,old.notes,old.filename,old.tags_text);
  INSERT INTO books_fts(rowid,title,author,publisher,genre,isbn,notes,filename,tags_text)
  VALUES (new.id,new.title,new.author,new.publisher,new.genre,new.isbn,new.notes,new.filename,new.tags_text);
END;
