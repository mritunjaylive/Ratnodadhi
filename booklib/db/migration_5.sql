-- migration_5.sql – V5: rename journal, conversion log, goals, temp-file registry
-- NOTE: The ALTER TABLE books ADD COLUMN converted_from is handled in _migrate_v5()
--       in database.py with a try/except to be idempotent.

-- conversion log
CREATE TABLE IF NOT EXISTS conversion_log (
    id             INTEGER PRIMARY KEY,
    source_book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    output_book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    from_format    TEXT NOT NULL,
    to_format      TEXT NOT NULL,
    started_at     TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at    TEXT,
    status         TEXT NOT NULL,          -- 'running' | 'done' | 'failed' | 'cancelled'
    error_tail     TEXT
);

-- rename journal (write-ahead, enables crash recovery and undo)
CREATE TABLE IF NOT EXISTS rename_batches (
    id             TEXT PRIMARY KEY,       -- uuid
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    folder_pattern TEXT,
    file_pattern   TEXT NOT NULL,
    undone_at      TEXT
);
CREATE TABLE IF NOT EXISTS rename_log (
    id           INTEGER PRIMARY KEY,
    batch_id     TEXT NOT NULL REFERENCES rename_batches(id) ON DELETE CASCADE,
    book_id      INTEGER REFERENCES books(id) ON DELETE SET NULL,
    old_path     TEXT NOT NULL,
    new_path     TEXT NOT NULL,
    created_dirs TEXT,                     -- JSON list of directories this step created
    status       TEXT NOT NULL,            -- 'pending' | 'done' | 'failed' | 'undone'
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_rename_log_batch ON rename_log(batch_id);

-- yearly reading goals
CREATE TABLE IF NOT EXISTS goals (
    id         INTEGER PRIMARY KEY,
    year       INTEGER NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('books','pages')),
    target     INTEGER NOT NULL CHECK (target > 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (year, kind)
);

-- statistics indices
CREATE INDEX IF NOT EXISTS idx_reading_log_finished ON reading_log(finished_on);
CREATE INDEX IF NOT EXISTS idx_reading_log_started  ON reading_log(started_on);

-- registry of temporary files created outside the app's own folders
CREATE TABLE IF NOT EXISTS temp_files (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    purpose    TEXT NOT NULL,              -- 'convert' | 'rename' | 'copy' | 'export' | 'backup'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_temp_files_created ON temp_files(created_at);
