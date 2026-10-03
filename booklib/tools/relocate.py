"""
relocate.py – Relocate local library folders when moving to a new path or PC.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from dataclasses import dataclass
from typing import Any

from booklib.db.repository import Repository

logger = logging.getLogger(__name__)


class RelocationError(ValueError):
    """Raised when relocation validation or execution fails."""
    pass


@dataclass
class RelocationResult:
    books_updated: int


def validate_relocation_target(
    conn_or_repo: Any,
    folder_id: int,
    new_root_path: str,
) -> tuple[int, int, float]:
    """
    Check how many of the folder's existing relative book paths exist under new_root_path.
    Returns (found_count, sample_size, percentage).
    """
    conn: sqlite3.Connection = conn_or_repo._conn if hasattr(conn_or_repo, "_conn") else conn_or_repo
    new_root = Path(new_root_path).resolve()
    if not new_root.exists() or not new_root.is_dir():
        raise RelocationError(f"Target path does not exist or is not a directory: {new_root_path}")

    row = conn.execute("SELECT path FROM folders WHERE id = ?", (folder_id,)).fetchone()
    if not row:
        raise RelocationError(f"Folder id {folder_id} not found.")

    old_root = Path(row[0]).resolve()

    # Get sample of up to 50 books in this folder
    book_rows = conn.execute(
        "SELECT path FROM books WHERE folder_id = ? AND source = 'local' LIMIT 50",
        (folder_id,)
    ).fetchall()

    if not book_rows:
        return (0, 0, 100.0)

    sample_size = len(book_rows)
    found_count = 0

    for r in book_rows:
        old_book_p = Path(r[0]).resolve()
        try:
            rel = old_book_p.relative_to(old_root)
            candidate = new_root / rel
            if candidate.exists():
                found_count += 1
        except ValueError:
            pass

    pct = (found_count / sample_size) * 100.0 if sample_size > 0 else 100.0
    return (found_count, sample_size, pct)


def relocate_folder(
    conn_or_repo: Any,
    folder_id: int,
    new_root_path: str,
) -> RelocationResult:
    """
    Rewrite folder path and all child book paths in a single atomic transaction.
    Matches folder prefix with trailing separator to prevent prefix collisions (e.g. C:\\Books vs C:\\Books2).
    Returns RelocationResult with count of updated book rows.
    """
    conn: sqlite3.Connection = conn_or_repo._conn if hasattr(conn_or_repo, "_conn") else conn_or_repo
    row = conn.execute("SELECT path, COALESCE(source, 'local') FROM folders WHERE id = ?", (folder_id,)).fetchone()
    if not row:
        raise RelocationError(f"Folder {folder_id} not found.")

    old_path_str, kind = row
    if kind == "gdrive":
        raise RelocationError("Cannot relocate a Google Drive folder; Drive folders use stable Drive IDs.")

    # Normalize paths with forward slashes for matching
    old_norm = old_path_str.replace("\\", "/").rstrip("/")
    new_norm = new_root_path.replace("\\", "/").rstrip("/")

    old_prefix = f"{old_norm}/"
    new_prefix = f"{new_norm}/"

    # Fetch books to rewrite
    books = conn.execute(
        "SELECT id, path FROM books WHERE folder_id = ? AND source = 'local'",
        (folder_id,)
    ).fetchall()

    updated_count = 0
    with conn:
        # Update folder row
        conn.execute("UPDATE folders SET path = ? WHERE id = ?", (new_norm, folder_id))

        for bid, bpath in books:
            norm_bpath = bpath.replace("\\", "/")
            if norm_bpath.startswith(old_prefix):
                new_bpath = norm_bpath.replace(old_prefix, new_prefix, 1)
                conn.execute("UPDATE books SET path = ?, is_missing = 0 WHERE id = ?", (new_bpath, bid))
                updated_count += 1
            elif norm_bpath == old_norm:
                conn.execute("UPDATE books SET path = ?, is_missing = 0 WHERE id = ?", (new_norm, bid))
                updated_count += 1

    logger.info("Relocated folder %d from %s to %s (%d books updated)", folder_id, old_norm, new_norm, updated_count)
    return RelocationResult(books_updated=updated_count)
