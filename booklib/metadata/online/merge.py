"""
merge.py – Field-level merging, genre cleaning, and metadata history undo.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any

from booklib.db import repository
from booklib.metadata.online.models import Candidate

logger = logging.getLogger(__name__)

_GENRE_BLOCKLIST = {
    "accessible book",
    "protected daisy",
    "in library",
    "large type books",
    "lending library",
    "general",
}


def clean_genres(raw_genres: list[str]) -> str | None:
    """
    Clean genre list:
    - Drop library noise (DAISY, lending library, nyt:, overdrive).
    - Split category hierarchies on '/' and take first 2.
    - Title-case and deduplicate.
    - Return at most 3 comma-separated genres.
    """
    cleaned: list[str] = []
    seen = set()

    for item in raw_genres:
        if not item or not isinstance(item, str):
            continue
        item_lower = item.strip().lower()
        if item_lower.startswith("nyt:") or item_lower.startswith("overdrive"):
            continue
        if item_lower in _GENRE_BLOCKLIST:
            continue

        # Split hierarchy if present (e.g. Fiction / Mystery & Detective / General)
        parts = [p.strip() for p in item.split('/')]
        for p in parts[:2]:
            p_clean = re.sub(r'[\s_]+', ' ', p).strip()
            p_lower = p_clean.lower()
            if not p_clean or p_lower in _GENRE_BLOCKLIST:
                continue
            if p_lower not in seen:
                seen.add(p_lower)
                cleaned.append(p_clean.title())
            if len(cleaned) >= 3:
                break
        if len(cleaned) >= 3:
            break

    return ", ".join(cleaned) if cleaned else None


def clean_authors(authors: list[str]) -> str | None:
    if not authors:
        return None
    cleaned: list[str] = []
    for a in authors:
        if not a or not isinstance(a, str):
            continue
        # If "Last, First", swap
        if ',' in a:
            parts = [p.strip() for p in a.split(',', 1)]
            if len(parts) == 2 and parts[1]:
                a = f"{parts[1]} {parts[0]}"
        a = re.sub(r'\s+', ' ', a).strip()
        if a and a not in cleaned:
            cleaned.append(a)
    return "; ".join(cleaned) if cleaned else None


def candidate_to_dict(cand: Candidate) -> dict[str, Any]:
    """Convert candidate fields to book field mappings."""
    out: dict[str, Any] = {}
    if cand.title:
        out["title"] = cand.title.strip()
    auths = clean_authors(cand.authors)
    if auths:
        out["author"] = auths
    if cand.publisher:
        out["publisher"] = cand.publisher.strip()
    if cand.year:
        out["year"] = cand.year
    if cand.isbn:
        out["isbn"] = cand.isbn.strip()
    if cand.pages:
        out["pages"] = cand.pages
    genres = clean_genres(cand.genres)
    if genres:
        out["genre"] = genres
    if cand.language:
        out["language"] = cand.language.strip().lower()[:2]
    if cand.description:
        out["description"] = cand.description.strip()
    return out


def apply_candidate(
    conn: sqlite3.Connection,
    book_id: int,
    cand: Candidate,
    batch_id: str,
    mode: str = "fill_only",  # 'fill_only' or 'replace'
    field_override: dict[str, bool] | None = None,  # field -> whether to apply
) -> dict[str, Any]:
    """
    Apply candidate fields to book in database respecting field_sources.
    Writes metadata_history row.
    Returns dict of actually changed fields: {field: (before, after)}.
    """
    # 1. Fetch current book state
    row = conn.execute(
        """SELECT title, author, publisher, year, isbn, pages, genre, language,
                  description, field_sources, lookup_status
           FROM books WHERE id = ?""",
        (book_id,)
    ).fetchone()

    if not row:
        return {}

    curr_data = {
        "title": row[0],
        "author": row[1],
        "publisher": row[2],
        "year": row[3],
        "isbn": row[4],
        "pages": row[5],
        "genre": row[6],
        "language": row[7],
        "description": row[8],
    }

    try:
        sources: dict[str, str] = json.loads(row[9]) if row[9] else {}
    except Exception:
        sources = {}

    cand_dict = candidate_to_dict(cand)
    changed: dict[str, tuple[Any, Any]] = {}
    before_json_dict: dict[str, Any] = {}
    after_json_dict: dict[str, Any] = {}

    for field, cand_val in cand_dict.items():
        if field_override is not None and not field_override.get(field, True):
            continue

        curr_val = curr_data.get(field)
        source = sources.get(field, "file")

        # Never touch manual edits
        if source == "manual":
            continue

        # In fill_only mode, only set if current value is empty/None
        if mode == "fill_only" and curr_val is not None and str(curr_val).strip() != "":
            continue

        # Don't update if value hasn't changed
        if curr_val == cand_val:
            continue

        # Apply field
        before_json_dict[field] = curr_val
        after_json_dict[field] = cand_val
        changed[field] = (curr_val, cand_val)
        curr_data[field] = cand_val
        sources[field] = f"online:{cand.provider}"

    if not changed:
        # Just record lookup_status = 'applied' if not already
        conn.execute(
            """UPDATE books SET lookup_status = 'applied', lookup_at = datetime('now'),
                                online_source = ?, online_id = ?
               WHERE id = ?""",
            (cand.provider, cand.provider_id, book_id),
        )
        return {}

    # 2. Write history row
    history_source = f"online:{cand.provider}"
    conn.execute(
        """INSERT INTO metadata_history (batch_id, book_id, source, before_json, after_json)
           VALUES (?, ?, ?, ?, ?)""",
        (batch_id, book_id, history_source, json.dumps(before_json_dict), json.dumps(after_json_dict)),
    )

    # 3. Update book
    set_clauses = [f"{f} = ?" for f in changed.keys()]
    set_clauses.extend([
        "field_sources = ?",
        "online_source = ?",
        "online_id = ?",
        "lookup_status = 'applied'",
        "lookup_at = datetime('now')",
    ])
    params = [after_json_dict[f] for f in changed.keys()]
    params.extend([json.dumps(sources), cand.provider, cand.provider_id, book_id])

    sql = f"UPDATE books SET {', '.join(set_clauses)} WHERE id = ?"
    conn.execute(sql, params)

    return changed


def undo_batch(conn: sqlite3.Connection, batch_id: str) -> int:
    """
    Undo a bulk or single online lookup batch.
    Only restores fields whose current value still matches after_json.
    Returns number of books updated.
    """
    rows = conn.execute(
        """SELECT id, book_id, before_json, after_json
           FROM metadata_history WHERE batch_id = ?""",
        (batch_id,)
    ).fetchall()

    if not rows:
        return 0

    undone_count = 0
    for hid, book_id, before_raw, after_raw in rows:
        try:
            before_dict = json.loads(before_raw)
            after_dict = json.loads(after_raw)
        except Exception:
            continue

        book_row = conn.execute(
            """SELECT title, author, publisher, year, isbn, pages, genre, language,
                      description, field_sources
               FROM books WHERE id = ?""",
            (book_id,)
        ).fetchone()

        if not book_row:
            continue

        curr_data = {
            "title": book_row[0],
            "author": book_row[1],
            "publisher": book_row[2],
            "year": book_row[3],
            "isbn": book_row[4],
            "pages": book_row[5],
            "genre": book_row[6],
            "language": book_row[7],
            "description": book_row[8],
        }

        try:
            sources: dict[str, str] = json.loads(book_row[9]) if book_row[9] else {}
        except Exception:
            sources = {}

        restore_fields: dict[str, Any] = {}
        for field, applied_val in after_dict.items():
            # Only restore if current value is still the value we applied
            if curr_data.get(field) == applied_val:
                restore_fields[field] = before_dict.get(field)
                # Reset source to file (or remove if None)
                if field in sources and sources[field].startswith("online:"):
                    sources[field] = "file"

        if restore_fields:
            set_parts = [f"{f} = ?" for f in restore_fields.keys()]
            set_parts.extend(["field_sources = ?", "lookup_status = NULL"])
            params = list(restore_fields.values())
            params.extend([json.dumps(sources), book_id])
            conn.execute(f"UPDATE books SET {', '.join(set_parts)} WHERE id = ?", params)
            undone_count += 1

    # Remove history entries for this batch
    conn.execute("DELETE FROM metadata_history WHERE batch_id = ?", (batch_id,))
    return undone_count
