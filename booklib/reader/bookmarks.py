"""
reader/bookmarks.py – Bookmarks CRUD, page mapping, and storage.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from booklib.reader.backend import Locator

logger = logging.getLogger(__name__)


def add_bookmark(
    conn: sqlite3.Connection,
    book_id: int,
    locator: Locator,
    label: str = "",
    snippet: str = "",
) -> int:
    """Insert a new bookmark and return its ID."""
    with conn:
        cur = conn.execute(
            """
            INSERT INTO bookmarks (book_id, locator, label, snippet, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (book_id, locator.to_json(), label or f"Bookmark on page {(locator.page or 0) + 1}", snippet[:80]),
        )
        return cur.lastrowid


def list_bookmarks(conn: sqlite3.Connection, book_id: int) -> list[dict[str, Any]]:
    """Return all bookmarks for a book ordered by creation time."""
    rows = conn.execute(
        "SELECT id, book_id, locator, label, snippet, created_at FROM bookmarks WHERE book_id = ? ORDER BY id ASC",
        (book_id,),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        d["locator_obj"] = Locator.from_json(r["locator"])
        res.append(d)
    return res


def rename_bookmark(conn: sqlite3.Connection, bookmark_id: int, label: str) -> None:
    """Update label of a bookmark."""
    with conn:
        conn.execute("UPDATE bookmarks SET label = ? WHERE id = ?", (label, bookmark_id))


def delete_bookmark(conn: sqlite3.Connection, bookmark_id: int) -> None:
    """Delete a bookmark by ID."""
    with conn:
        conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))


def get_bookmarked_pages(conn: sqlite3.Connection, book_id: int) -> set[int]:
    """Return set of page numbers (0-based) that currently have bookmarks."""
    rows = conn.execute("SELECT locator FROM bookmarks WHERE book_id = ?", (book_id,)).fetchall()
    pages = set()
    for r in rows:
        loc = Locator.from_json(r["locator"])
        if loc.page is not None:
            pages.add(loc.page)
    return pages
