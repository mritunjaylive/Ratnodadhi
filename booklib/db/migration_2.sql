-- migration_2.sql  -- Schema additions for v2
--
-- Run by database.py _migrate() when user_version == 1.
-- Table alterations are executed in Python via ALTER TABLE (with try/except).
-- This script creates the indices, tables, triggers, and FTS5 virtual table.
-- PRAGMA user_version is set in Python after success.

CREATE INDEX IF NOT EXISTS idx_books_status      ON books(status);
CREATE INDEX IF NOT EXISTS idx_books_rating      ON books(rating);
CREATE INDEX IF NOT EXISTS idx_books_format      ON books(format);
CREATE INDEX IF NOT EXISTS idx_books_date_added  ON books(date_added);
CREATE INDEX IF NOT EXISTS idx_books_last_opened ON books(last_opened_at);

CREATE TABLE IF NOT EXISTS custom_readers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    exe_path      TEXT NOT NULL,
    args_template TEXT NOT NULL DEFAULT '{file}',
    formats       TEXT NOT NULL DEFAULT '*'
);

CREATE TABLE IF NOT EXISTS format_defaults (
    format     TEXT PRIMARY KEY,
    reader_key TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
    title, author, publisher, genre, isbn, notes, filename,
    content='books', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
  INSERT INTO books_fts(rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES (new.id,new.title,new.author,new.publisher,new.genre,new.isbn,new.notes,new.filename);
END;

CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
  INSERT INTO books_fts(books_fts,rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES ('delete',old.id,old.title,old.author,old.publisher,old.genre,old.isbn,old.notes,old.filename);
END;

CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE OF title,author,publisher,genre,isbn,notes,filename ON books BEGIN
  INSERT INTO books_fts(books_fts,rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES ('delete',old.id,old.title,old.author,old.publisher,old.genre,old.isbn,old.notes,old.filename);
  INSERT INTO books_fts(rowid,title,author,publisher,genre,isbn,notes,filename)
  VALUES (new.id,new.title,new.author,new.publisher,new.genre,new.isbn,new.notes,new.filename);
END;
