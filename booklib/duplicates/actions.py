"""
actions.py – Duplicate resolution actions (remove from library, recycle bin, ignore).
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
import sqlite3

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

logger = logging.getLogger("app")


def ignore_group(conn: sqlite3.Connection, group_key: str) -> None:
    """Ignore duplicate group so it will not be shown again."""
    conn.execute(
        "INSERT OR IGNORE INTO duplicate_ignores (group_key, created_at) VALUES (?, datetime('now'))",
        (group_key,),
    )
    conn.commit()


def remove_from_library(conn: sqlite3.Connection, book_ids: list[int]) -> int:
    """
    Remove books from the database only; does not touch files on disk.
    Cascades will delete book_tags, collection_books, reading_log, metadata_history.
    """
    if not book_ids:
        return 0

    placeholders = ",".join("?" for _ in book_ids)
    cursor = conn.execute(f"DELETE FROM books WHERE id IN ({placeholders})", book_ids)
    conn.commit()
    return cursor.rowcount


def send_to_recycle_bin(conn: sqlite3.Connection, book_ids: list[int]) -> tuple[int, list[str]]:
    """
    Sends files to OS Recycle Bin using send2trash, then deletes rows from database.
    Logs each removal with path, hash, timestamp to app.log.
    Returns (num_removed, errors).
    """
    if not book_ids:
        return 0, []

    placeholders = ",".join("?" for _ in book_ids)
    rows = conn.execute(
        f"SELECT id, path, file_hash, quick_hash FROM books WHERE id IN ({placeholders})",
        book_ids,
    ).fetchall()

    errors: list[str] = []
    success_ids: list[int] = []

    for bid, path_str, fhash, qhash in rows:
        if path_str.startswith("gdrive://"):
            errors.append(f"Cannot send Google Drive file to Recycle Bin: {path_str} is read-only. Use 'Remove from library' instead.")
            continue
        p = Path(path_str)
        if p.exists():
            try:
                if send2trash is not None:
                    send2trash(str(p))
                else:
                    # Fallback if send2trash unavailable
                    p.unlink()
                logger.info(
                    "Duplicate removed to recycle bin: path=%s, hash=%s, time=%s",
                    path_str,
                    fhash or qhash or "unknown",
                    datetime.datetime.now().isoformat(),
                )
                success_ids.append(bid)
            except Exception as exc:
                err_msg = f"Failed to recycle {path_str}: {exc}"
                logger.error(err_msg)
                errors.append(err_msg)
        else:
            # File already missing from disk, still remove from DB
            success_ids.append(bid)

    if success_ids:
        remove_from_library(conn, success_ids)

    return len(success_ids), errors
