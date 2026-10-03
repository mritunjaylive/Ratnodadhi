"""
porting/matcher.py – Match import rows to existing books in the library.

Match order (first hit wins):
  1. drive_file_id  (exact)
  2. md5 or file_hash (exact)
  3. Valid unique ISBN  (skipped if multiple books share it)
  4. title_key + author_key  (v3 normalizers; skipped if ambiguous)
  5. Relative file path

Ambiguous title/author matches are flagged (status='ambiguous') and listed
separately; a caller can do a manual pick.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass
class MatchResult:
    row_index: int
    import_data: dict[str, Any]
    matched_book_ids: list[int]     # 0 = no match, 1 = matched, >1 = ambiguous
    match_method: str               # 'drive_id' | 'md5' | 'isbn' | 'title_author' | 'path' | 'none'
    status: str                     # 'matched' | 'ambiguous' | 'unmatched'


def _normalize(text: str) -> str:
    """Normalize text for fuzzy title/author matching (v3 convention)."""
    text = unicodedata.normalize("NFC", (text or "").lower())
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def match_rows(
    conn: sqlite3.Connection,
    import_rows: list[dict[str, Any]],
    apply_to_all_isbn_matches: bool = True,
) -> list[MatchResult]:
    """
    Match each import row to books in the library.
    Returns one MatchResult per row.
    """
    results = []
    for i, row in enumerate(import_rows):
        result = _match_one(conn, i, row, apply_to_all_isbn_matches)
        results.append(result)
    return results


def _match_one(
    conn: sqlite3.Connection,
    idx: int,
    row: dict[str, Any],
    apply_to_all_isbn: bool,
) -> MatchResult:

    def make(ids: list[int], method: str) -> MatchResult:
        if not ids:
            return MatchResult(idx, row, [], method, "unmatched")
        if len(ids) == 1:
            return MatchResult(idx, row, ids, method, "matched")
        return MatchResult(idx, row, ids, method, "ambiguous")

    # 1. drive_file_id
    if drive_id := row.get("key", {}).get("drive_file_id") if isinstance(row.get("key"), dict) else None:
        ids = _fetch_ids(conn, "SELECT id FROM books WHERE drive_file_id = ?", (drive_id,))
        if ids:
            return make(ids, "drive_id")

    # 2. md5
    md5 = (row.get("key", {}) or {}).get("md5") or row.get("md5")
    if md5:
        ids = _fetch_ids(conn, "SELECT id FROM books WHERE md5 = ?", (md5,))
        if ids:
            return make(ids, "md5")

    # 3. ISBN (unique)
    isbn = _clean_isbn(row)
    if isbn:
        ids = _fetch_ids(conn, "SELECT id FROM books WHERE isbn = ?", (isbn,))
        if ids:
            if len(ids) > 1 and not apply_to_all_isbn:
                return MatchResult(idx, row, ids, "isbn", "ambiguous")
            return make(ids, "isbn")

    # 4. title + author (normalized)
    title = row.get("title") or (row.get("key", {}) or {}).get("title")
    author = row.get("author") or (row.get("key", {}) or {}).get("author")
    if title and author:
        tk = _normalize(title)
        ak = _normalize(author)
        # Fetch all books and compare normalized keys
        all_books = conn.execute(
            "SELECT id, title, author FROM books WHERE is_missing = 0"
        ).fetchall()
        ids = [
            b["id"] for b in all_books
            if _normalize(b["title"] or "") == tk and _normalize(b["author"] or "") == ak
        ]
        if ids:
            if len(ids) > 1:
                return MatchResult(idx, row, ids, "title_author", "ambiguous")
            return make(ids, "title_author")

    # 5. Relative file path
    path = (row.get("key", {}) or {}).get("path") or row.get("path")
    if path:
        ids = _fetch_ids(conn, "SELECT id FROM books WHERE path = ?", (path,))
        if ids:
            return make(ids, "path")

    return MatchResult(idx, row, [], "none", "unmatched")


def _fetch_ids(conn: sqlite3.Connection, sql: str, params: tuple) -> list[int]:
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def _clean_isbn(row: dict) -> str:
    raw = (
        (row.get("key", {}) or {}).get("isbn")
        or row.get("isbn")
        or ""
    )
    cleaned = re.sub(r"[^0-9X]", "", str(raw).upper())
    if len(cleaned) in (10, 13):
        return cleaned
    return ""
