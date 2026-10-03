"""
finder.py – Duplicate book finder with exact, same-ISBN, and similar title/author levels.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import sqlite3
import unicodedata
from typing import Any

from booklib.duplicates.hashing import compute_full_hash

logger = logging.getLogger(__name__)

_NOISE_WORDS = {"the", "a", "an", "edition", "ed", "revised", "pdf", "epub", "vol", "volume"}


def make_title_key(title: str | None) -> str:
    if not title:
        return ""
    # Strip bracketed tags [PDF] and parenthesized text like (2nd Edition)
    cleaned = re.sub(r'\[[^\]]*\]|\([^\)]*\)', '', title)
    # Remove accents
    s = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    # Lowercase & remove punctuation
    s = re.sub(r'[^\w\s]', ' ', s.lower())
    words = s.split()
    # Strip leading article and noise words
    filtered = [w for w in words if w not in _NOISE_WORDS]
    return " ".join(filtered).strip()



def make_author_key(author: str | None) -> str:
    if not author:
        return ""
    s = unicodedata.normalize("NFKD", author).encode("ascii", "ignore").decode("ascii")
    # Take first author
    first = re.split(r'[,;]|\band\b', s, flags=re.IGNORECASE)[0].strip()
    words = re.sub(r'[^\w\s]', '', first.lower()).split()
    if not words:
        return ""
    # If "Last, First" was given, the last word or first word could be surname. Return the last word
    return words[-1]


@dataclass
class DuplicateGroup:
    group_key: str
    level: str  # 'exact' | 'same_isbn' | 'similar'
    book_ids: list[int]
    books: list[dict[str, Any]]
    suggested_keeper_id: int
    reclaimable_bytes: int


def _score_keeper(b: dict[str, Any]) -> tuple[int, int, int]:
    """Score for keeper preference: (completeness_count, pages, -id)."""
    fields = ["title", "author", "publisher", "year", "isbn", "pages", "genre", "description"]
    completeness = sum(1 for f in fields if b.get(f))
    pages = b.get("pages") or 0
    neg_id = -(b.get("id") or 0)
    return (completeness, pages, neg_id)


def find_duplicate_groups(conn: sqlite3.Connection) -> list[DuplicateGroup]:
    """
    Finds duplicate groups across the library:
    1. Exact duplicates (by file_hash, backfilling file_hash for potential collisions).
    2. Same ISBN duplicates.
    3. Similar title and author duplicates.
    Filters out groups present in duplicate_ignores.
    """
    # 0. Fetch ignored group keys
    ignored_rows = conn.execute("SELECT group_key FROM duplicate_ignores").fetchall()
    ignored_set = {r[0] for r in ignored_rows}

    # 1. Backfill file_hash for local books sharing size_bytes and quick_hash
    cand_collisions = conn.execute(
        """SELECT size_bytes, quick_hash FROM books
           WHERE quick_hash IS NOT NULL AND is_missing = 0 AND source = 'local'
           GROUP BY size_bytes, quick_hash HAVING COUNT(*) > 1"""
    ).fetchall()

    for size_b, qhash in cand_collisions:
        rows_to_hash = conn.execute(
            """SELECT id, path FROM books
               WHERE size_bytes = ? AND quick_hash = ? AND file_hash IS NULL AND is_missing = 0 AND source = 'local'""",
            (size_b, qhash),
        ).fetchall()
        for bid, path in rows_to_hash:
            if not path.startswith("gdrive://"):
                fhash = compute_full_hash(path)
                if fhash:
                    conn.execute("UPDATE books SET file_hash = ? WHERE id = ?", (fhash, bid))

    # 1b. Lazy MD5 computation for local books sharing size with Drive books
    try:
        drive_sizes = conn.execute(
            "SELECT DISTINCT size_bytes FROM books WHERE source = 'drive' AND md5 IS NOT NULL AND is_missing = 0"
        ).fetchall()
        d_sizes = [r[0] for r in drive_sizes if r[0]]
        if d_sizes:
            placeholders = ",".join("?" * len(d_sizes))
            local_to_md5 = conn.execute(
                f"SELECT id, path FROM books WHERE source = 'local' AND size_bytes IN ({placeholders}) AND md5 IS NULL AND is_missing = 0",
                d_sizes
            ).fetchall()
            from booklib.drive.download import compute_file_md5
            for bid, p in local_to_md5:
                if Path(p).exists():
                    try:
                        cmd5 = compute_file_md5(Path(p))
                        conn.execute("UPDATE books SET md5 = ? WHERE id = ?", (cmd5, bid))
                    except Exception:
                        pass
    except Exception as e:
        logger.warning("Error in lazy MD5 duplicate calculation: %s", e)

    conn.commit()

    # 2. Fetch all books
    cursor = conn.execute(
        """SELECT id, title, author, publisher, year, isbn, pages, genre,
                  format, size_bytes, path, filename, status, rating, date_added AS added_at, date_added,
                  file_hash, quick_hash, description, source, drive_path, md5, drive_file_id
           FROM books WHERE is_missing = 0"""
    )
    cols = [d[0] for d in cursor.description]
    all_books = [dict(zip(cols, row)) for row in cursor.fetchall()]
    books_by_id = {b["id"]: b for b in all_books}

    already_grouped_ids: set[int] = set()
    result_groups: list[DuplicateGroup] = []

    # ── Level 1: Exact duplicates (file_hash or identical md5) ──────────────
    hash_map: dict[str, list[int]] = {}
    for b in all_books:
        # Prefer full file_hash, or md5 if available
        key = None
        if b.get("file_hash"):
            key = f"fh:{b['file_hash']}"
        elif b.get("md5"):
            key = f"md5:{b['md5']}"
        if key:
            hash_map.setdefault(key, []).append(b["id"])

    # Also match across file_hash and md5 if local book has computed md5
    md5_map: dict[str, list[int]] = {}
    for b in all_books:
        m = b.get("md5")
        if m:
            md5_map.setdefault(m, []).append(b["id"])

    # Combine exact groups
    combined_exact: list[list[int]] = []
    for ids in hash_map.values():
        if len(ids) > 1:
            combined_exact.append(ids)
    for ids in md5_map.values():
        if len(ids) > 1 and ids not in combined_exact:
            combined_exact.append(ids)

    for ids in combined_exact:
        sorted_ids = sorted(set(ids))
        if len(sorted_ids) > 1:
            gkey = f"exact:{','.join(map(str, sorted_ids))}"
            if gkey not in ignored_set and not any(bid in already_grouped_ids for bid in sorted_ids):
                b_list = [books_by_id[bid] for bid in sorted_ids]
                keeper_id = max(b_list, key=_score_keeper)["id"]
                rec_bytes = sum(b.get("size_bytes") or 0 for b in b_list if b["id"] != keeper_id)
                result_groups.append(
                    DuplicateGroup(
                        group_key=gkey,
                        level="exact",
                        book_ids=sorted_ids,
                        books=b_list,
                        suggested_keeper_id=keeper_id,
                        reclaimable_bytes=rec_bytes,
                    )
                )
                already_grouped_ids.update(sorted_ids)

    # ── Level 2: Same ISBN ──────────────────────────────────────────────────
    isbn_map: dict[str, list[int]] = {}
    for b in all_books:
        bid = b["id"]
        if bid in already_grouped_ids:
            continue
        raw_isbn = b.get("isbn")
        if raw_isbn:
            clean = re.sub(r'[\s\-]+', '', raw_isbn)
            if len(clean) in (10, 13):
                isbn_map.setdefault(clean, []).append(bid)

    for clean_isbn, ids in isbn_map.items():
        if len(ids) > 1:
            sorted_ids = sorted(ids)
            gkey = f"same_isbn:{','.join(map(str, sorted_ids))}"
            if gkey not in ignored_set:
                b_list = [books_by_id[bid] for bid in sorted_ids]
                keeper_id = max(b_list, key=_score_keeper)["id"]
                rec_bytes = sum(b.get("size_bytes") or 0 for b in b_list if b["id"] != keeper_id)
                result_groups.append(
                    DuplicateGroup(
                        group_key=gkey,
                        level="same_isbn",
                        book_ids=sorted_ids,
                        books=b_list,
                        suggested_keeper_id=keeper_id,
                        reclaimable_bytes=rec_bytes,
                    )
                )
                already_grouped_ids.update(ids)

    # ── Level 3: Similar title and author ────────────────────────────────────
    sim_map: dict[tuple[str, str], list[int]] = {}
    for b in all_books:
        bid = b["id"]
        if bid in already_grouped_ids:
            continue
        t_key = make_title_key(b.get("title"))
        a_key = make_author_key(b.get("author"))
        if t_key and len(t_key) >= 3:
            sim_map.setdefault((t_key, a_key), []).append(bid)

    for (t_key, a_key), ids in sim_map.items():
        if len(ids) > 1:
            sorted_ids = sorted(ids)
            gkey = f"similar:{','.join(map(str, sorted_ids))}"
            if gkey not in ignored_set:
                b_list = [books_by_id[bid] for bid in sorted_ids]
                keeper_id = max(b_list, key=_score_keeper)["id"]
                rec_bytes = sum(b.get("size_bytes") or 0 for b in b_list if b["id"] != keeper_id)
                result_groups.append(
                    DuplicateGroup(
                        group_key=gkey,
                        level="similar",
                        book_ids=sorted_ids,
                        books=b_list,
                        suggested_keeper_id=keeper_id,
                        reclaimable_bytes=rec_bytes,
                    )
                )
                already_grouped_ids.update(ids)

    return result_groups
