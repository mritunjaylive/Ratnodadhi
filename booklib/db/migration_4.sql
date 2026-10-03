-- Migration 4: Google Drive Integration & Storage Management
-- Backup file: library.db.bak-v3

-- accounts
CREATE TABLE IF NOT EXISTS drive_accounts (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    changes_token TEXT,                            -- Drive Changes API page token
    state         TEXT NOT NULL DEFAULT 'ok',      -- 'ok' | 'needs_signin'
    added_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync_at  TEXT
);

-- mirror of the Drive folder tree under synced roots (used for ancestry checks in sync)
CREATE TABLE IF NOT EXISTS drive_nodes (
    account_id INTEGER NOT NULL REFERENCES drive_accounts(id) ON DELETE CASCADE,
    file_id    TEXT NOT NULL,
    parent_id  TEXT,
    name       TEXT NOT NULL,
    root_folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    PRIMARY KEY (account_id, file_id)
);

-- downloaded copies
CREATE TABLE IF NOT EXISTS drive_cache (
    book_id       INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    file_path     TEXT NOT NULL,               -- relative to the cache folder
    size_bytes    INTEGER NOT NULL,
    md5           TEXT,
    downloaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_opened_at TEXT,
    in_use_until  TEXT                         -- lease: do not evict before this UTC time
);
CREATE INDEX IF NOT EXISTS idx_drive_cache_used ON drive_cache(last_used_at);

-- small key/value store (last backup time, etc.)
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
