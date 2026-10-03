"""
merge.py – Merge user data from duplicate books into the keeper book.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from booklib.db import repository

logger = logging.getLogger(__name__)

_STATUS_RANK = {
    "read": 3,
    "reading": 2,
    "want": 1,
    None: 0,
    "": 0,
}


def merge_book_user_data(
    conn: sqlite3.Connection,
    keeper_id: int,
    duplicate_ids: list[int],
) -> None:
    """
    Merges user data from duplicate books into keeper_id:
    - Status: highest rank ('read' > 'reading' > 'want')
    - Rating: keeper rating if set (> 0), otherwise highest from duplicates
    - Notes: merged with separator
    - Tags: union of tag associations
    - Collections: union of collection associations
    - Reading log: union of reading log rows
    - Progress: largest progress_page / progress_percent
    """
    all_ids = [keeper_id] + [d for d in duplicate_ids if d != keeper_id]

    # Fetch status, rating, notes, progress for all books
    cursor = conn.execute(
        f"""SELECT id, status, rating, notes, progress_page, progress_percent
            FROM books WHERE id IN ({','.join('?' for _ in all_ids)})""",
        all_ids,
    )
    rows = cursor.fetchall()
    by_id = {r[0]: r for r in rows}

    if keeper_id not in by_id:
        return

    k_row = by_id[keeper_id]
    best_status = k_row[1]
    best_rank = _STATUS_RANK.get(best_status, 0)
    best_rating = k_row[2] or 0
    k_notes = (k_row[3] or "").strip()
    notes_list = [k_notes] if k_notes else []
    max_page = k_row[4] or 0
    max_pct = k_row[5] or 0.0

    for dup_id in duplicate_ids:
        if dup_id == keeper_id or dup_id not in by_id:
            continue
        d_row = by_id[dup_id]
        d_status = d_row[1]
        d_rank = _STATUS_RANK.get(d_status, 0)
        if d_rank > best_rank:
            best_status = d_status
            best_rank = d_rank

        d_rating = d_row[2] or 0
        if best_rating == 0 and d_rating > 0:
            best_rating = d_rating

        d_notes = (d_row[3] or "").strip()
        if d_notes and d_notes not in notes_list:
            notes_list.append(d_notes)

        d_page = d_row[4] or 0
        if d_page > max_page:
            max_page = d_page

        d_pct = d_row[5] or 0.0
        if d_pct > max_pct:
            max_pct = d_pct

    merged_notes = "\n---\n".join(notes_list) if notes_list else None

    # Update keeper book row
    conn.execute(
        """UPDATE books
           SET status = ?, rating = ?, notes = ?,
               progress_page = CASE WHEN ? > 0 THEN ? ELSE progress_page END,
               progress_percent = CASE WHEN ? > 0.0 THEN ? ELSE progress_percent END
           WHERE id = ?""",
        (
            best_status,
            best_rating if best_rating > 0 else None,
            merged_notes,
            max_page,
            max_page,
            max_pct,
            max_pct,
            keeper_id,
        ),
    )

    # 1. Union tags: insert into book_tags for keeper
    for dup_id in duplicate_ids:
        if dup_id == keeper_id:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO book_tags (book_id, tag_id)
               SELECT ?, tag_id FROM book_tags WHERE book_id = ?""",
            (keeper_id, dup_id),
        )

    # Rebuild tags_text on keeper
    tag_names = [
        r[0]
        for r in conn.execute(
            """SELECT t.name FROM tags t
               JOIN book_tags bt ON bt.tag_id = t.id
               WHERE bt.book_id = ? ORDER BY t.name""",
            (keeper_id,),
        ).fetchall()
    ]
    conn.execute("UPDATE books SET tags_text = ? WHERE id = ?", (" ".join(tag_names), keeper_id))

    # 2. Union collections: insert into collection_books for keeper
    for dup_id in duplicate_ids:
        if dup_id == keeper_id:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO collection_books (collection_id, book_id, added_at)
               SELECT collection_id, ?, added_at FROM collection_books WHERE book_id = ?""",
            (keeper_id, dup_id),
        )

    # 3. Union reading_log: copy non-duplicate reading_log entries to keeper
    for dup_id in duplicate_ids:
        if dup_id == keeper_id:
            continue
        conn.execute(
            """INSERT INTO reading_log (book_id, started_on, finished_on, note)
               SELECT ?, started_on, finished_on, note FROM reading_log WHERE book_id = ?""",
            (keeper_id, dup_id),
        )
