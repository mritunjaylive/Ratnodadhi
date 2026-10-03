"""
cache.py – Database operations, pinning, and query helpers for drive_cache.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from booklib.config import DRIVE_CACHE_DIR
from booklib.storage.planner import CleanupPlan, CleanupAction
from booklib.storage.executor import execute_cleanup


def _resolve_conn(conn_or_repo: Any) -> sqlite3.Connection:
    if hasattr(conn_or_repo, "_conn"):
        return conn_or_repo._conn
    if hasattr(conn_or_repo, "conn"):
        return conn_or_repo.conn
    return conn_or_repo


def is_book_downloaded(conn_or_repo: Any, book_id: int) -> bool:
    """Return True if book has an entry in drive_cache and file exists on disk."""
    conn = _resolve_conn(conn_or_repo)
    row = conn.execute("SELECT file_path FROM drive_cache WHERE book_id = ?", (book_id,)).fetchone()
    if not row:
        return False
    return (DRIVE_CACHE_DIR / row[0]).exists()


def get_cached_path(conn_or_repo: Any, book_id: int) -> Path | None:
    """Return absolute Path to cached file if present, else None."""
    conn = _resolve_conn(conn_or_repo)
    row = conn.execute("SELECT file_path FROM drive_cache WHERE book_id = ?", (book_id,)).fetchone()
    if not row:
        return None
    p = DRIVE_CACHE_DIR / row[0]
    return p if p.exists() else None


def set_book_pinned(conn_or_repo: Any, book_id: int, pinned: bool) -> None:
    """Set keep_offline flag on book."""
    conn = _resolve_conn(conn_or_repo)
    conn.execute("UPDATE books SET keep_offline = ? WHERE id = ?", (1 if pinned else 0, book_id))
    conn.commit()


def is_book_pinned(conn_or_repo: Any, book_id: int) -> bool:
    conn = _resolve_conn(conn_or_repo)
    row = conn.execute("SELECT keep_offline FROM books WHERE id = ?", (book_id,)).fetchone()
    return bool(row[0]) if row else False


def evict_book(conn_or_repo: Any, book_id: int, force: bool = False) -> bool:
    """
    Remove a book's cached download from disk and database.
    If book is pinned or leased, returns False unless force=True.
    """
    conn = _resolve_conn(conn_or_repo)
    row = conn.execute(
        """SELECT c.file_path, c.size_bytes, b.keep_offline, c.in_use_until
           FROM drive_cache c
           JOIN books b ON c.book_id = b.id
           WHERE c.book_id = ?""",
        (book_id,)
    ).fetchone()

    if not row:
        return False

    file_path, size_bytes, is_pinned, in_use_until = row
    if not force and is_pinned:
        return False

    plan = CleanupPlan(
        actions=[
            CleanupAction(
                area="drive_downloads",
                path=DRIVE_CACHE_DIR / file_path,
                book_id=book_id,
                size_bytes=size_bytes,
                reason_text="Manual eviction",
            )
        ]
    )
    deleted, _, _ = execute_cleanup(conn, plan)
    return deleted > 0


def clear_drive_cache(conn_or_repo: Any, include_pinned: bool = False) -> tuple[int, int]:
    """
    Clear all cached Drive downloads, optionally including pinned files.
    Returns (files_deleted, bytes_freed).
    """
    conn = _resolve_conn(conn_or_repo)
    sql = """
        SELECT c.book_id, c.file_path, c.size_bytes, b.keep_offline
        FROM drive_cache c
        JOIN books b ON c.book_id = b.id
    """
    if not include_pinned:
        sql += " WHERE b.keep_offline = 0"

    rows = conn.execute(sql).fetchall()
    actions = []
    for r in rows:
        book_id = r["book_id"] if isinstance(r, sqlite3.Row) or isinstance(r, dict) else r[0]
        file_path = r["file_path"] if isinstance(r, sqlite3.Row) or isinstance(r, dict) else r[1]
        size_bytes = r["size_bytes"] if isinstance(r, sqlite3.Row) or isinstance(r, dict) else r[2]
        actions.append(
            CleanupAction(
                area="drive_downloads",
                path=DRIVE_CACHE_DIR / file_path,
                book_id=book_id,
                size_bytes=size_bytes,
                reason_text="Clear cache operation",
            )
        )

    plan = CleanupPlan(actions=actions)
    deleted, freed, _ = execute_cleanup(conn, plan)
    return deleted, freed
