"""
porting/apply.py – Apply an import to matched books.

- Sets field_sources[field] = "import:<kind>" (protected like manual)
- Writes metadata_history rows for undo
- Handles reading_log entries
- Uses fill-empty-only (default) or overwrite mode
- Safety snapshot before applying
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from booklib.porting.matcher import MatchResult

logger = logging.getLogger(__name__)

# Fields that come from the import rows and map directly to book columns
_DIRECT_FIELDS = {
    "title", "author", "publisher", "year", "pages", "isbn",
    "genre", "language", "description", "notes", "rating",
    "series", "series_index",
}

# Status values
_VALID_STATUSES = {"want", "reading", "read"}


def apply_import(
    conn: sqlite3.Connection,
    matches: list[MatchResult],
    import_kind: str,                 # 'booklib' | 'goodreads' | 'csv'
    overwrite: bool = False,
    fields_to_import: set[str] | None = None,
) -> dict:
    """
    Apply matched import data to the library.

    *import_kind*: used as the field_sources value prefix ("import:goodreads", etc.)
    *overwrite*: if False (default), only fill empty fields.
    *fields_to_import*: None = all available fields.

    Returns a summary dict: {matched, changed, fields_changed, errors}
    """
    # Safety snapshot
    try:
        from booklib.backup.safety import take_snapshot
        take_snapshot(f"before import ({import_kind})")
    except Exception as exc:
        logger.warning("Safety snapshot failed before import: %s", exc)

    source_tag = f"import:{import_kind}"
    changed_books = 0
    total_fields = 0
    errors: list[str] = []

    matched = [m for m in matches if m.status == "matched"]

    for match in matched:
        for book_id in match.matched_book_ids:
            try:
                n = _apply_one(
                    conn, book_id, match.import_data, source_tag,
                    overwrite, fields_to_import,
                )
                if n > 0:
                    changed_books += 1
                    total_fields += n
            except Exception as exc:
                errors.append(f"Book {book_id}: {exc}")
                logger.warning("Import error for book %d: %s", book_id, exc)

    return {
        "matched": len(matched),
        "changed": changed_books,
        "fields_changed": total_fields,
        "errors": errors,
    }


def _apply_one(
    conn: sqlite3.Connection,
    book_id: int,
    data: dict[str, Any],
    source_tag: str,
    overwrite: bool,
    fields_to_import: set[str] | None,
) -> int:
    """Apply data to one book. Returns number of fields changed."""
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        return 0
    book = dict(book)

    field_sources: dict = {}
    try:
        field_sources = json.loads(book.get("field_sources") or "{}")
    except Exception:
        pass

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    updates: dict[str, Any] = {}
    changed = 0

    def _should_update(field: str, new_val: Any) -> bool:
        if fields_to_import and field not in fields_to_import:
            return False
        if new_val is None or new_val == "":
            return False
        current = book.get(field)
        if overwrite:
            return current != new_val
        # Fill-empty-only
        return current is None or current == "" or current == 0

    # Direct metadata fields
    for f in _DIRECT_FIELDS:
        val = data.get(f)
        if val is not None and _should_update(f, val):
            before[f] = book.get(f)
            after[f] = val
            updates[f] = val
            field_sources[f] = source_tag
            changed += 1

    # Status
    status = data.get("status")
    if status in _VALID_STATUSES and (fields_to_import is None or "status" in fields_to_import):
        if overwrite or not book.get("status"):
            before["status"] = book.get("status")
            after["status"] = status
            updates["status"] = status
            changed += 1

    # Apply DB updates
    if updates:
        updates["field_sources"] = json.dumps(field_sources)
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE books SET {set_clause} WHERE id = ?",
            [*updates.values(), book_id],
        )

    # Reading log (finished_on from import)
    finished_on = data.get("finished_on")
    reading_log_entries = data.get("reading_log", [])
    if isinstance(reading_log_entries, list):
        for entry in reading_log_entries:
            _upsert_reading_log(conn, book_id, entry.get("started_on"), entry.get("finished_on"))
    elif finished_on:
        _upsert_reading_log(conn, book_id, data.get("started_on"), finished_on)

    # Tags
    tags = data.get("tags")
    if tags and isinstance(tags, list) and (fields_to_import is None or "tags" in fields_to_import):
        _apply_tags(conn, book_id, tags, overwrite)

    # History row for undo
    if before or after:
        conn.execute(
            """INSERT INTO metadata_history (book_id, source, before_json, after_json)
               VALUES (?, ?, ?, ?)""",
            (book_id, source_tag, json.dumps(before), json.dumps(after)),
        )

    conn.commit()
    return changed


def _upsert_reading_log(
    conn: sqlite3.Connection,
    book_id: int,
    started_on: str | None,
    finished_on: str | None,
) -> None:
    if not finished_on and not started_on:
        return
    # Check if a matching entry already exists
    existing = conn.execute(
        """SELECT id FROM reading_log
           WHERE book_id = ? AND (finished_on = ? OR (finished_on IS NULL AND ? IS NULL))""",
        (book_id, finished_on, finished_on),
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO reading_log (book_id, started_on, finished_on) VALUES (?, ?, ?)",
            (book_id, started_on or None, finished_on or None),
        )


def _apply_tags(
    conn: sqlite3.Connection,
    book_id: int,
    tag_names: list[str],
    overwrite: bool,
) -> None:
    """Add tags to the book (overwrite = replace existing)."""
    if overwrite:
        conn.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))

    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        tag_row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if tag_row:
            tag_id = tag_row["id"]
        else:
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            tag_id = cur.lastrowid
        # Ignore duplicates
        conn.execute(
            "INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)",
            (book_id, tag_id),
        )
