"""
porting/export_csv.py – Export library books to UTF-8-with-BOM CSV.

- RFC 4180 quoting
- Multi-value fields joined with "; "
- Dates as ISO YYYY-MM-DD, booleans as 0/1
- Spreadsheet formula protection (cells starting with = + - @ tab CR prefixed with ')
- Field presets: Basic, All
"""
from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from typing import Any, Iterable

# ── Field definitions ─────────────────────────────────────────────────────────

BASIC_FIELDS = [
    "title", "author", "publisher", "year", "edition", "isbn",
    "pages", "genre", "language", "format", "size_bytes", "status",
    "rating", "tags", "series", "series_index", "date_added",
]

ALL_FIELDS = BASIC_FIELDS + [
    "notes", "collections", "started_on", "finished_on",
    "progress_page", "progress_percent",
    "source", "drive_path", "md5", "description", "path",
    "lookup_status",
]

_FORMULA_STARTERS = ("=", "+", "-", "@", "\t", "\r")


def _protect(cell: str) -> str:
    """Prefix formula-like cells with a single quote."""
    if cell and cell[0] in _FORMULA_STARTERS:
        return "'" + cell
    return cell


def export_csv(
    conn: sqlite3.Connection,
    dest_path: Path,
    book_ids: list[int] | None = None,
    fields: list[str] | None = None,
    include_file_paths: bool = False,
    formula_protection: bool = True,
) -> int:
    """
    Write books to *dest_path* as UTF-8-with-BOM CSV.

    *book_ids*: None = all; list = specific books.
    *fields*: None = BASIC_FIELDS preset.
    Returns the number of rows written.
    """
    fields = fields or BASIC_FIELDS
    if not include_file_paths and "path" in fields:
        fields = [f for f in fields if f != "path"]

    books = _load_books(conn, book_ids)
    rows_written = 0

    # Write to temp name first, then rename on success
    tmp = dest_path.with_suffix(dest_path.suffix + ".tmp-write")
    try:
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(fields)
            for book in books:
                row = _book_to_row(book, fields, formula_protection)
                writer.writerow(row)
                rows_written += 1
        tmp.replace(dest_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    return rows_written


def _load_books(conn: sqlite3.Connection, book_ids: list[int] | None) -> list[dict]:
    if book_ids:
        placeholders = ",".join("?" * len(book_ids))
        rows = conn.execute(
            f"SELECT * FROM books WHERE id IN ({placeholders}) ORDER BY title COLLATE NOCASE",
            book_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM books WHERE is_missing = 0 ORDER BY title COLLATE NOCASE"
        ).fetchall()
    return [dict(r) for r in rows]


def _book_to_row(book: dict, fields: list[str], protect: bool) -> list[str]:
    cells = []
    for f in fields:
        raw = book.get(f)
        if raw is None:
            cells.append("")
        elif f in ("tags", "collections", "genres"):
            # These may be stored as JSON arrays or semicolon strings
            cells.append(_multi_value(raw, protect))
        elif isinstance(raw, bool):
            cells.append("1" if raw else "0")
        elif isinstance(raw, int):
            cells.append(str(raw))
        elif isinstance(raw, float):
            cells.append(f"{raw:g}")
        else:
            text = str(raw)
            cells.append(_protect(text) if protect else text)
    return cells


def _multi_value(raw: Any, protect: bool) -> str:
    import json
    if isinstance(raw, list):
        parts = raw
    else:
        try:
            parts = json.loads(str(raw))
            if not isinstance(parts, list):
                parts = [str(raw)]
        except (json.JSONDecodeError, TypeError):
            parts = [p.strip() for p in str(raw).split(";") if p.strip()]
    joined = "; ".join(str(p) for p in parts)
    return _protect(joined) if protect else joined
