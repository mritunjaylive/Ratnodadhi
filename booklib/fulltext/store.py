"""
fulltext/store.py – fulltext.db storage, schema, incremental vacuum, and chunk index management.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from booklib.config import FULLTEXT_DB_PATH
from booklib.fulltext.chunker import Chunk

logger = logging.getLogger(__name__)


class FullTextStore:
    """Manages fulltext.db containing chunks and contentless FTS5 virtual table."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else FULLTEXT_DB_PATH
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        # Set pragmas before tables created
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")

        self._create_schema(conn)
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    chapter_index INTEGER,
                    page_number INTEGER,
                    chunk_index INTEGER,
                    token_start INTEGER,
                    token_end INTEGER,
                    char_count INTEGER,
                    text TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id);")

            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                    text,
                    content='',
                    contentless_delete=1,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )

    # ── Chunk Storage ─────────────────────────────────────────────────────────

    def store_book_chunks(self, book_id: int, chunks: list[Chunk]) -> int:
        """Replace all chunks for a book and sync with chunk_fts."""
        conn = self.connect()
        with conn:
            # 1. Delete existing chunks for this book
            rows = conn.execute("SELECT id FROM chunks WHERE book_id = ?", (book_id,)).fetchall()
            if rows:
                chunk_ids = [r[0] for r in rows]
                for cid in chunk_ids:
                    conn.execute("DELETE FROM chunk_fts WHERE rowid = ?", (cid,))
                conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))

            # 2. Insert new chunks
            for c in chunks:
                cur = conn.execute(
                    """
                    INSERT INTO chunks (book_id, chapter_index, page_number, chunk_index, token_start, token_end, char_count, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c.book_id,
                        c.chapter_index,
                        c.page_number,
                        c.chunk_index,
                        c.token_start,
                        c.token_end,
                        c.char_count,
                        c.text,
                    ),
                )
                chunk_id = cur.lastrowid
                conn.execute("INSERT INTO chunk_fts (rowid, text) VALUES (?, ?)", (chunk_id, c.text))

        return len(chunks)

    def delete_book_chunks(self, book_id: int) -> int:
        """Remove all chunks and FTS entries for a book."""
        conn = self.connect()
        with conn:
            rows = conn.execute("SELECT id FROM chunks WHERE book_id = ?", (book_id,)).fetchall()
            for r in rows:
                conn.execute("DELETE FROM chunk_fts WHERE rowid = ?", (r[0],))
            cur = conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
            return cur.rowcount

    def delete_all(self) -> None:
        """Clear all chunks and reset FTS index."""
        conn = self.connect()
        with conn:
            conn.execute("DELETE FROM chunk_fts;")
            conn.execute("DELETE FROM chunks;")
        self.compact()

    def get_indexed_book_ids(self) -> set[int]:
        """Return set of book IDs currently present in the index."""
        conn = self.connect()
        rows = conn.execute("SELECT DISTINCT book_id FROM chunks").fetchall()
        return {r[0] for r in rows}

    # ── Database Maintenance & Space ──────────────────────────────────────────

    def get_size_bytes(self) -> int:
        """Return current on-disk size of fulltext.db."""
        if self.db_path.exists():
            return self.db_path.stat().st_size
        return 0

    def compact(self, full_vacuum: bool = False) -> None:
        """Reclaim space via incremental vacuum (or full vacuum)."""
        conn = self.connect()
        if full_vacuum:
            conn.execute("VACUUM;")
        else:
            conn.execute("PRAGMA incremental_vacuum(1000);")

    def trim_old_index(self, library_conn: sqlite3.Connection, max_days: int) -> int:
        """
        Remove index for books not opened in the last max_days (or never opened).
        Returns number of books trimmed.
        """
        # Find candidate books
        cutoff_modifier = f"-{int(max_days)} days"
        rows = library_conn.execute(
            """
            SELECT id FROM books
            WHERE fts_state = 'indexed'
              AND (last_opened_at IS NULL OR last_opened_at < datetime('now', ?))
            ORDER BY (last_opened_at IS NULL) DESC, last_opened_at ASC
            """,
            (cutoff_modifier,),
        ).fetchall()

        if not rows:
            return 0

        trimmed_count = 0
        for r in rows:
            bid = r[0]
            self.delete_book_chunks(bid)
            with library_conn:
                library_conn.execute(
                    "UPDATE books SET fts_state = NULL, text_chars = NULL, fts_indexed_at = NULL WHERE id = ?",
                    (bid,),
                )
            trimmed_count += 1

        self.compact()
        return trimmed_count

    def remove_folder_index(self, library_conn: sqlite3.Connection, folder_id: int) -> int:
        """Remove index for all books within a given folder."""
        rows = library_conn.execute(
            "SELECT id FROM books WHERE folder_id = ? AND fts_state = 'indexed'",
            (folder_id,),
        ).fetchall()
        trimmed_count = 0
        for r in rows:
            bid = r[0]
            self.delete_book_chunks(bid)
            with library_conn:
                library_conn.execute(
                    "UPDATE books SET fts_state = NULL, text_chars = NULL, fts_indexed_at = NULL WHERE id = ?",
                    (bid,),
                )
            trimmed_count += 1

        if trimmed_count > 0:
            self.compact()
        return trimmed_count


_default_store: FullTextStore | None = None


def get_fulltext_store(db_path: Path | str | None = None) -> FullTextStore:
    global _default_store
    if _default_store is None:
        _default_store = FullTextStore(db_path)
    return _default_store
