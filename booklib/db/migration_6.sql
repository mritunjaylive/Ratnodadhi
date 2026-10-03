-- migration 6 (core)
-- Reading positions, bookmarks, annotations, sessions, recommendations, web devices

-- 1. Reading positions (one per book)
CREATE TABLE IF NOT EXISTS reading_positions (
    book_id    INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    locator    TEXT NOT NULL,          -- JSON
    progress   REAL,                   -- 0..1 under layout when saved
    layout_key TEXT,                   -- font size, margins, page size layout
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. Bookmarks
CREATE TABLE IF NOT EXISTS bookmarks (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    locator    TEXT NOT NULL,
    label      TEXT,
    snippet    TEXT,                   -- first words on page
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_book ON bookmarks(book_id);

-- 3. Annotations (highlights and notes)
CREATE TABLE IF NOT EXISTS annotations (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL DEFAULT 'highlight',   -- 'highlight' | 'underline' | 'note'
    color      TEXT NOT NULL DEFAULT 'yellow',
    quote      TEXT NOT NULL,          -- selected text
    prefix     TEXT,                   -- ~30 chars before
    suffix     TEXT,                   -- ~30 chars after
    locator    TEXT NOT NULL,          -- JSON
    note       TEXT,
    state      TEXT NOT NULL DEFAULT 'ok',          -- 'ok' | 'orphaned'
    origin     TEXT NOT NULL DEFAULT 'app',         -- 'app' | 'file'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_annotations_book ON annotations(book_id);

-- 4. Annotations FTS
CREATE VIRTUAL TABLE IF NOT EXISTS annotations_fts USING fts5(
    quote, note, content='annotations', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS annotations_ai AFTER INSERT ON annotations BEGIN
    INSERT INTO annotations_fts(rowid, quote, note) VALUES (new.id, new.quote, new.note);
END;

CREATE TRIGGER IF NOT EXISTS annotations_ad AFTER DELETE ON annotations BEGIN
    INSERT INTO annotations_fts(annotations_fts, rowid, quote, note) VALUES ('delete', old.id, old.quote, old.note);
END;

CREATE TRIGGER IF NOT EXISTS annotations_au AFTER UPDATE OF quote, note ON annotations BEGIN
    INSERT INTO annotations_fts(annotations_fts, rowid, quote, note) VALUES ('delete', old.id, old.quote, old.note);
    INSERT INTO annotations_fts(rowid, quote, note) VALUES (new.id, new.quote, new.note);
END;

-- 5. Reading sessions (active reading time tracking)
CREATE TABLE IF NOT EXISTS reading_sessions (
    id             INTEGER PRIMARY KEY,
    book_id        INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    started_at     TEXT NOT NULL,      -- local ISO datetime
    ended_at       TEXT,
    active_seconds INTEGER NOT NULL DEFAULT 0,
    start_progress REAL,
    end_progress   REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON reading_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_book    ON reading_sessions(book_id);

-- 6. Recommendation feedback
CREATE TABLE IF NOT EXISTS recommendation_feedback (
    book_id    INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    verdict    TEXT NOT NULL CHECK (verdict IN ('hide','not_interested')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 7. Web access: paired devices
CREATE TABLE IF NOT EXISTS web_devices (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,  -- SHA-256 of random device token
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT,
    last_ip      TEXT,
    revoked_at   TEXT
);
