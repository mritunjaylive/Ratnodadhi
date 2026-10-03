"""
reader/position.py – Reading position persistence, progress updates, and V3 status rules.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from booklib.reader.backend import Locator

logger = logging.getLogger(__name__)


def save_reading_position(
    conn: sqlite3.Connection,
    book_id: int,
    locator: Locator,
    progress: float,
    layout_key: str = "",
) -> None:
    """Upsert reading position and update book progress in database."""
    loc_json = locator.to_json()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO reading_positions (book_id, locator, progress, layout_key, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(book_id) DO UPDATE SET
                    locator = excluded.locator,
                    progress = excluded.progress,
                    layout_key = excluded.layout_key,
                    updated_at = datetime('now')
                """,
                (book_id, loc_json, progress, layout_key),
            )

            # Update book progress percentage
            pct = round(progress * 100.0, 1)
            conn.execute(
                """
                UPDATE books SET
                    progress_percent = ?,
                    last_opened_at = datetime('now')
                WHERE id = ?
                """,
                (pct, book_id),
            )

            # Apply V3 status transition: Want to Read -> Reading
            row = conn.execute("SELECT status FROM books WHERE id = ?", (book_id,)).fetchone()
            if row and (row["status"] is None or row["status"] == "want"):
                conn.execute(
                    """
                    UPDATE books SET
                        status = 'reading',
                        status_changed_at = datetime('now')
                    WHERE id = ?
                    """,
                    (book_id,),
                )
    except Exception as exc:
        logger.warning("Failed to save reading position for book %d: %s", book_id, exc)


def load_reading_position(
    conn: sqlite3.Connection,
    book_id: int,
) -> tuple[Locator | None, float | None, str | None]:
    """Load saved reading position: (locator, progress, layout_key)."""
    try:
        row = conn.execute(
            "SELECT locator, progress, layout_key FROM reading_positions WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        if row:
            loc = Locator.from_json(row["locator"])
            return (loc, row["progress"], row["layout_key"])
    except Exception as exc:
        logger.warning("Failed to load reading position for book %d: %s", book_id, exc)
    return (None, None, None)
