"""
database.py – SQLite connection management and schema migrations.

Usage:
    db = Database()
    db.connect()   # opens/creates the database, applies migrations
    db.close()
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

from booklib.config import DB_PATH

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 6

# FTS5 availability check (almost always True with CPython)
_fts5_available: bool | None = None


def fts5_available() -> bool:
    global _fts5_available
    if _fts5_available is None:
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE VIRTUAL TABLE _t USING fts5(x)")
            conn.close()
            _fts5_available = True
        except sqlite3.OperationalError:
            _fts5_available = False
    return _fts5_available


def natural_compare(a: str, b: str) -> int:
    """Case-insensitive natural sort: 'Book 2' < 'Book 10'."""
    import re

    def key(s: str) -> list:
        parts = re.split(r"(\d+)", (s or "").lower())
        return [int(p) if p.isdigit() else p for p in parts]

    ka, kb = key(a), key(b)
    return (ka > kb) - (ka < kb)


class Database:
    """Manages the SQLite connection and applies numbered migrations."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._path = db_path
        self.conn: sqlite3.Connection | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        """Open (or create) the database, run migrations, return connection."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            str(self._path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        self._apply_pragmas(self.conn)
        self._register_collation(self.conn)
        self._migrate()
        logger.info("Database opened at %s (schema v%d)", self._path, CURRENT_SCHEMA_VERSION)
        return self.conn

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def new_connection(self) -> sqlite3.Connection:
        """Return a separate connection for a background thread."""
        conn = sqlite3.connect(
            str(self._path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        self._apply_pragmas(conn)
        self._register_collation(conn)
        return conn

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")

    @staticmethod
    def _register_collation(conn: sqlite3.Connection) -> None:
        conn.create_collation("NATURAL", natural_compare)

    def _migrate(self) -> None:
        assert self.conn
        version: int = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self._run_sql_file("schema.sql")
            self.conn.execute("PRAGMA user_version = 1")
            self.conn.commit()
            logger.info("Applied migration: v1 schema")
            version = 1

        if version < 2:
            self._migrate_v2()
            version = 2

        if version < 3:
            self._migrate_v3()
            version = 3

        if version < 4:
            self._migrate_v4()
            version = 4

        if version < 5:
            self._migrate_v5()
            version = 5

        if version < 6:
            self._migrate_v6()
            version = 6

    def _run_sql_file(self, filename: str) -> None:
        """Execute a .sql file through executescript (handles -- comments)."""
        assert self.conn
        sql = (Path(__file__).parent / filename).read_text(encoding="utf-8")
        # Strip PRAGMA lines — pragmas must run outside executescript's implicit
        # transaction (executescript always commits first).
        ddl_lines = [
            line for line in sql.splitlines()
            if not line.strip().upper().startswith("PRAGMA")
        ]
        self.conn.executescript("\n".join(ddl_lines))

    def _migrate_v2(self) -> None:
        """Apply migration 2 (backup first, then ALTER + FTS)."""
        assert self.conn

        # ── Backup ────────────────────────────────────────────────────────────
        bak = self._path.with_suffix(".db.bak-v1")
        if self._path.exists() and not bak.exists():
            shutil.copy2(str(self._path), str(bak))
            logger.info("Database backed up to %s", bak)

        # ── New columns (ALTER TABLE – ignore if already exists) ──────────────
        _alters = [
            "ALTER TABLE books ADD COLUMN status_changed_at TEXT",
            "ALTER TABLE books ADD COLUMN last_opened_at    TEXT",
            "ALTER TABLE books ADD COLUMN open_count        INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE books ADD COLUMN edited_fields     TEXT",
        ]
        for stmt in _alters:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists

        # ── New tables, indices, FTS ──────────────────────────────────────────
        if fts5_available():
            self._run_sql_file("migration_2.sql")
        else:
            # FTS not available: create everything except the FTS virtual table
            logger.warning("FTS5 not available; search will use LIKE fallback")
            sql = (Path(__file__).parent / "migration_2.sql").read_text(encoding="utf-8")
            # Remove FTS-related lines
            filtered = [
                l for l in sql.splitlines()
                if not any(kw in l.upper() for kw in
                           ["FTS5", "BOOKS_FTS", "BOOKS_AI", "BOOKS_AD", "BOOKS_AU",
                            "VIRTUAL TABLE", "TRIGGER"])
            ]
            self.conn.executescript("\n".join(filtered))

        # ── Populate FTS from existing rows ───────────────────────────────────
        if fts5_available():
            try:
                self.conn.execute("INSERT INTO books_fts(books_fts) VALUES ('rebuild')")
            except sqlite3.OperationalError:
                pass

        cur_v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if cur_v < 2:
            self.conn.execute("PRAGMA user_version = 2")
        self.conn.commit()
        logger.info("Applied migration: v2 schema")


    def _migrate_v3(self) -> None:
        """Apply migration 3 (backup first, then ALTER + new tables + data conversions)."""
        import json
        assert self.conn

        # ── Backup ────────────────────────────────────────────────────────────
        bak = self._path.with_suffix(".db.bak-v2")
        if self._path.exists() and not bak.exists():
            shutil.copy2(str(self._path), str(bak))
            logger.info("Database backed up to %s", bak)

        # ── New columns in books and folders ──────────────────────────────────
        _alters = [
            "ALTER TABLE books ADD COLUMN field_sources    TEXT",
            "ALTER TABLE books ADD COLUMN description      TEXT",
            "ALTER TABLE books ADD COLUMN online_source    TEXT",
            "ALTER TABLE books ADD COLUMN online_id        TEXT",
            "ALTER TABLE books ADD COLUMN lookup_status    TEXT",
            "ALTER TABLE books ADD COLUMN lookup_at        TEXT",
            "ALTER TABLE books ADD COLUMN cover_source     TEXT NOT NULL DEFAULT 'file'",
            "ALTER TABLE books ADD COLUMN quick_hash       TEXT",
            "ALTER TABLE books ADD COLUMN series_id        INTEGER REFERENCES series(id) ON DELETE SET NULL",
            "ALTER TABLE books ADD COLUMN series_index     REAL",
            "ALTER TABLE books ADD COLUMN progress_page    INTEGER",
            "ALTER TABLE books ADD COLUMN progress_percent REAL",
            "ALTER TABLE books ADD COLUMN tags_text        TEXT",
            "ALTER TABLE folders ADD COLUMN watch          INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE folders ADD COLUMN auto_lookup    INTEGER NOT NULL DEFAULT 0",
        ]
        for stmt in _alters:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists

        # ── New tables, indices, triggers and FTS ─────────────────────────────
        self._run_sql_file("migration_3.sql")

        # ── Data conversions ──────────────────────────────────────────────────
        # 1. Field provenance: convert edited_fields to field_sources
        try:
            rows = self.conn.execute("SELECT id, edited_fields FROM books WHERE edited_fields IS NOT NULL").fetchall()
            for r in rows:
                if r["edited_fields"]:
                    try:
                        edited = json.loads(r["edited_fields"])
                        if edited:
                            sources = {f: "manual" for f in edited}
                            self.conn.execute(
                                "UPDATE books SET field_sources = ? WHERE id = ?",
                                (json.dumps(sources), r["id"])
                            )
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Field sources migration notice: %s", e)

        # 2. Reading history: migrate reading / read statuses to reading_log
        try:
            self.conn.execute("""
                INSERT INTO reading_log (book_id, started_on)
                SELECT id, COALESCE(date(status_changed_at), date('now'))
                FROM books WHERE status = 'reading'
            """)
            self.conn.execute("""
                INSERT INTO reading_log (book_id, finished_on)
                SELECT id, COALESCE(date(status_changed_at), date('now'))
                FROM books WHERE status = 'read'
            """)
        except Exception as e:
            logger.warning("Reading log migration notice: %s", e)

        # 3. Cover source: set placeholder for formats that do not have real covers
        try:
            self.conn.execute("""
                UPDATE books
                SET cover_source = CASE
                    WHEN format IN ('mobi', 'azw3', 'djvu', 'txt') THEN 'placeholder'
                    ELSE 'file'
                END
                WHERE cover_source IS NULL OR cover_source = 'file'
            """)
        except Exception as e:
            logger.warning("Cover source migration notice: %s", e)

        # ── Populate FTS from existing rows ───────────────────────────────────
        if fts5_available():
            try:
                self.conn.execute("INSERT INTO books_fts(books_fts) VALUES ('rebuild')")
            except sqlite3.OperationalError:
                pass

        cur_v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if cur_v < 3:
            self.conn.execute("PRAGMA user_version = 3")
        self.conn.commit()
        logger.info("Applied migration: v3 schema")

    def _migrate_v4(self) -> None:
        """Apply migration 4 (backup first, then ALTER + Drive & Cache tables)."""
        assert self.conn

        # ── Backup ────────────────────────────────────────────────────────────
        bak = self._path.with_suffix(".db.bak-v3")
        if self._path.exists() and not bak.exists():
            shutil.copy2(str(self._path), str(bak))
            logger.info("Database backed up to %s", bak)

        # ── New columns in folders ────────────────────────────────────────────
        _folder_alters = [
            "ALTER TABLE folders ADD COLUMN kind              TEXT NOT NULL DEFAULT 'local'",
            "ALTER TABLE folders ADD COLUMN source            TEXT NOT NULL DEFAULT 'local'",
            "ALTER TABLE folders ADD COLUMN account_id        INTEGER REFERENCES drive_accounts(id) ON DELETE CASCADE",
            "ALTER TABLE folders ADD COLUMN drive_folder_id   TEXT",
            "ALTER TABLE folders ADD COLUMN drive_display     TEXT",
            "ALTER TABLE folders ADD COLUMN sync_token        TEXT",
            "ALTER TABLE folders ADD COLUMN include_subfolders INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE folders ADD COLUMN deep_index        INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE folders ADD COLUMN sync_enabled      INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE folders ADD COLUMN sync_auto         INTEGER NOT NULL DEFAULT 1",
        ]
        for stmt in _folder_alters:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

        # ── New columns in books ──────────────────────────────────────────────
        _book_alters = [
            "ALTER TABLE books ADD COLUMN source         TEXT NOT NULL DEFAULT 'local'",
            "ALTER TABLE books ADD COLUMN drive_file_id  TEXT",
            "ALTER TABLE books ADD COLUMN md5            TEXT",
            "ALTER TABLE books ADD COLUMN drive_path     TEXT",
            "ALTER TABLE books ADD COLUMN drive_web_link TEXT",
            "ALTER TABLE books ADD COLUMN index_level    TEXT NOT NULL DEFAULT 'full'",
            "ALTER TABLE books ADD COLUMN keep_offline   INTEGER NOT NULL DEFAULT 0",
        ]
        for stmt in _book_alters:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

        # ── New tables from migration_4.sql ───────────────────────────────────
        self._run_sql_file("migration_4.sql")

        # ── Indices ───────────────────────────────────────────────────────────
        _indices = [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_books_drive_file ON books(drive_file_id) WHERE drive_file_id IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_books_source ON books(source)",
            "CREATE INDEX IF NOT EXISTS idx_books_md5 ON books(md5)",
        ]
        for stmt in _indices:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

        cur_v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if cur_v < 4:
            self.conn.execute("PRAGMA user_version = 4")
        self.conn.commit()
        logger.info("Applied migration: v4 schema")

    def _migrate_v5(self) -> None:
        """Apply migration 5 (backup first, then rename journal, conversion log, goals, temp registry)."""
        assert self.conn

        # ── Backup ────────────────────────────────────────────────────────────
        bak = self._path.with_suffix(".db.bak-v4")
        if self._path.exists() and not bak.exists():
            shutil.copy2(str(self._path), str(bak))
            logger.info("Database backed up to %s", bak)

        # ── New column on books ───────────────────────────────────────────────
        _book_alters = [
            "ALTER TABLE books ADD COLUMN converted_from INTEGER REFERENCES books(id) ON DELETE SET NULL",
        ]
        for stmt in _book_alters:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists

        # Index for the new column (IF NOT EXISTS is safe)
        try:
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_books_converted_from ON books(converted_from)"
            )
        except sqlite3.OperationalError:
            pass

        # ── New tables and indices from migration_5.sql ───────────────────────
        self._run_sql_file("migration_5.sql")

        cur_v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if cur_v < 5:
            self.conn.execute("PRAGMA user_version = 5")
        self.conn.commit()
        logger.info("Applied migration: v5 schema")

    def _migrate_v6(self) -> None:
        """Apply migration 6 (reading positions, bookmarks, annotations, sessions, fts columns)."""
        assert self.conn

        # ── Backup ────────────────────────────────────────────────────────────
        bak = self._path.with_suffix(".db.bak-v5")
        if self._path.exists() and not bak.exists():
            shutil.copy2(str(self._path), str(bak))
            logger.info("Database backed up to %s", bak)

        try:
            from booklib.backup.safety import take_snapshot
            take_snapshot("migration-v6")
        except Exception as exc:
            logger.warning("Safety snapshot during migration 6 failed: %s", exc)

        # ── New columns in books ──────────────────────────────────────────────
        _book_alters = [
            "ALTER TABLE books ADD COLUMN fts_state      TEXT",
            "ALTER TABLE books ADD COLUMN fts_version    INTEGER",
            "ALTER TABLE books ADD COLUMN fts_indexed_at TEXT",
            "ALTER TABLE books ADD COLUMN text_chars     INTEGER",
        ]
        for stmt in _book_alters:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

        # ── New column in folders ─────────────────────────────────────────────
        try:
            self.conn.execute(
                "ALTER TABLE folders ADD COLUMN index_contents INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass

        # ── Migration 6b: Cloud Provider Abstraction ──────────────────────────
        try:
            self.conn.execute(
                "ALTER TABLE drive_accounts ADD COLUMN provider TEXT NOT NULL DEFAULT 'gdrive'"
            )
        except sqlite3.OperationalError:
            pass

        try:
            self.conn.execute("ALTER TABLE books ADD COLUMN remote_hash_kind TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            self.conn.execute("ALTER TABLE books ADD COLUMN remote_hash TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            self.conn.execute(
                "UPDATE books SET remote_hash = md5, remote_hash_kind = 'md5' "
                "WHERE md5 IS NOT NULL AND (remote_hash IS NULL OR remote_hash_kind IS NULL)"
            )
        except sqlite3.OperationalError:
            pass

        # ── New tables, triggers, and indices from migration_6.sql ───────────
        if fts5_available():
            self._run_sql_file("migration_6.sql")
            try:
                self.conn.execute("INSERT INTO annotations_fts(annotations_fts) VALUES ('rebuild')")
            except sqlite3.OperationalError:
                pass
        else:
            # Without FTS5, strip annotations_fts virtual table & triggers
            sql = (Path(__file__).parent / "migration_6.sql").read_text(encoding="utf-8")
            filtered = [
                l for l in sql.splitlines()
                if not any(kw in l.upper() for kw in
                           ["ANNOTATIONS_FTS", "ANNOTATIONS_AI", "ANNOTATIONS_AD", "ANNOTATIONS_AU",
                            "VIRTUAL TABLE", "TRIGGER"])
            ]
            self.conn.executescript("\n".join(filtered))

        cur_v = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if cur_v < 6:
            self.conn.execute("PRAGMA user_version = 6")
        self.conn.commit()
        logger.info("Applied migration: v6 schema")
