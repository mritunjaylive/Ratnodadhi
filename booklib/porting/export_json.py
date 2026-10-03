"""
porting/export_json.py – Export library to BookLib JSON format.

Format:
  {
    "format": "booklib-export",
    "version": 1,
    "exported_at": "...",
    "app_version": "5.0",
    "schema_version": 5,
    "books": [...],
    "collections": [...]
  }

Never includes tokens, credentials, or the Google client file.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


APP_VERSION = "5.0"
EXPORT_FORMAT_VERSION = 1


def export_json(
    conn: sqlite3.Connection,
    dest_path: Path,
    book_ids: list[int] | None = None,
    include_file_paths: bool = True,
) -> int:
    """
    Write books to *dest_path* as BookLib JSON.
    Returns the number of books written.
    """
    books_data = _load_books_json(conn, book_ids, include_file_paths)
    collections = _load_collections(conn)

    payload = {
        "format": "booklib-export",
        "version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "app_version": APP_VERSION,
        "schema_version": 5,
        "books": books_data,
        "collections": collections,
    }

    tmp = dest_path.with_suffix(dest_path.suffix + ".tmp-write")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        tmp.replace(dest_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    return len(books_data)


def _load_books_json(
    conn: sqlite3.Connection,
    book_ids: list[int] | None,
    include_paths: bool,
) -> list[dict]:
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

    result = []
    for r in rows:
        book = dict(r)
        reading_log = conn.execute(
            "SELECT started_on, finished_on FROM reading_log WHERE book_id = ? ORDER BY id",
            (book["id"],),
        ).fetchall()
        tags = conn.execute(
            "SELECT t.name FROM tags t JOIN book_tags bt ON bt.tag_id = t.id WHERE bt.book_id = ?",
            (book["id"],),
        ).fetchall()
        collections = conn.execute(
            """SELECT c.name FROM collections c
               JOIN collection_books cb ON cb.collection_id = c.id
               WHERE cb.book_id = ?""",
            (book["id"],),
        ).fetchall()

        entry: dict[str, Any] = {
            "key": {
                "isbn": book.get("isbn"),
                "md5": book.get("md5"),
                "drive_file_id": book.get("drive_file_id"),
                "path": book.get("path") if include_paths else None,
                "size_bytes": book.get("size_bytes"),
            },
            "title": book.get("title"),
            "author": book.get("author"),
            "publisher": book.get("publisher"),
            "year": book.get("year"),
            "pages": book.get("pages"),
            "isbn": book.get("isbn"),
            "genre": book.get("genre"),
            "language": book.get("language"),
            "format": book.get("format"),
            "status": book.get("status"),
            "rating": book.get("rating"),
            "notes": book.get("notes"),
            "description": book.get("description"),
            "series": {"name": book.get("series_name"), "index": book.get("series_index")},
            "tags": [t["name"] for t in tags],
            "collections": [c["name"] for c in collections],
            "reading_log": [
                {"started_on": rl["started_on"], "finished_on": rl["finished_on"]}
                for rl in reading_log
            ],
            "field_sources": _parse_json_field(book.get("field_sources")),
            "date_added": book.get("date_added"),
            "last_opened_at": book.get("last_opened_at"),
        }

        if book.get("converted_from"):
            entry["converted_from_id"] = book["converted_from"]

        result.append(entry)
    return result


def _load_collections(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT name, kind, smart_query FROM collections ORDER BY name COLLATE NOCASE"
    ).fetchall()
    result = []
    for r in rows:
        entry: dict[str, Any] = {"name": r["name"], "kind": r["kind"]}
        if r["kind"] == "smart" and r["smart_query"]:
            entry["smart_query"] = _parse_json_field(r["smart_query"])
        result.append(entry)
    return result


def _parse_json_field(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        import json
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return raw
