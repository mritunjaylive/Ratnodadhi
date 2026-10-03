"""
repository.py – all SQL queries and data-access methods live here.

v3 additions: field provenance (field_sources), tags, collections (manual & smart),
series, reading log & history, reading progress, online lookups & caching,
metadata history & batch undo, duplicate detection & merging, file relinking,
and custom cover management.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from booklib.db.query import LibraryQuery, VALID_SORT_FIELDS, build_fts_query


# ── Lightweight book record for library views ─────────────────────────────────

@dataclass
class BookRow:
    id: int
    title: str | None
    author: str | None
    year: int | None
    size_bytes: int
    format: str
    pages: int | None
    cover_path: str | None
    date_added: str
    is_missing: bool
    path: str
    status: str | None = None
    rating: int | None = None
    last_opened_at: str | None = None
    open_count: int = 0
    publisher: str | None = None
    genre: str | None = None
    language: str | None = None
    isbn: str | None = None
    edition: str | None = None
    # v3 fields
    field_sources: dict[str, str] = field(default_factory=dict)
    description: str | None = None
    cover_source: str = "file"
    series_id: int | None = None
    series_name: str | None = None
    series_index: float | None = None
    progress_page: int | None = None
    progress_percent: float | None = None
    lookup_status: str | None = None
    tags_text: str | None = None
    # v4 fields
    source: str = "local"
    drive_file_id: str | None = None
    md5: str | None = None
    drive_path: str | None = None
    drive_web_link: str | None = None
    index_level: str = "full"
    keep_offline: bool = False
    is_cached: bool = False
    cached_path: str | None = None


@dataclass
class BookDetail:
    id: int
    title: str | None
    author: str | None
    publisher: str | None
    year: int | None
    edition: str | None
    isbn: str | None
    pages: int | None
    genre: str | None
    language: str | None
    size_bytes: int
    format: str
    path: str
    cover_path: str | None
    date_added: str
    is_missing: bool
    status: str | None = None
    rating: int | None = None
    notes: str | None = None
    last_opened_at: str | None = None
    open_count: int = 0
    edited_fields: list[str] = field(default_factory=list)
    # v3 fields
    field_sources: dict[str, str] = field(default_factory=dict)
    description: str | None = None
    online_source: str | None = None
    online_id: str | None = None
    lookup_status: str | None = None
    lookup_at: str | None = None
    cover_source: str = "file"
    quick_hash: str | None = None
    file_hash: str | None = None
    series_id: int | None = None
    series_name: str | None = None
    series_index: float | None = None
    progress_page: int | None = None
    progress_percent: float | None = None
    # v4 fields
    source: str = "local"
    drive_file_id: str | None = None
    md5: str | None = None
    drive_path: str | None = None
    drive_web_link: str | None = None
    index_level: str = "full"
    keep_offline: bool = False
    is_cached: bool = False
    cached_path: str | None = None
    tags: list[dict[str, Any]] = field(default_factory=list)
    collections: list[dict[str, Any]] = field(default_factory=list)
    reading_log: list[dict[str, Any]] = field(default_factory=list)


# ── Repository ────────────────────────────────────────────────────────────────

class Repository:
    """Data-access layer. Accepts a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._use_fts = self._check_fts()

    def _check_fts(self) -> bool:
        try:
            self._conn.execute("SELECT rowid FROM books_fts LIMIT 1")
            return True
        except sqlite3.OperationalError:
            return False

    # ── Folders ───────────────────────────────────────────────────────────────

    def add_folder(self, path: str, watch: bool = False, auto_lookup: bool = False) -> int:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO folders (path, watch, auto_lookup) VALUES (?, ?, ?)",
            (path, 1 if watch else 0, 1 if auto_lookup else 0),
        )
        self._conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = self._conn.execute("SELECT id FROM folders WHERE path = ?", (path,)).fetchone()
        return row["id"]

    def remove_folder(self, folder_id: int) -> None:
        self._conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        self._conn.commit()

    def list_folders(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, path, added_at, last_scanned_at, watch, auto_lookup FROM folders ORDER BY path"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_folder_scanned(self, folder_id: int) -> None:
        self._conn.execute(
            "UPDATE folders SET last_scanned_at = datetime('now') WHERE id = ?",
            (folder_id,),
        )
        self._conn.commit()

    def set_folder_watch(self, folder_id: int, watch: bool) -> None:
        self._conn.execute("UPDATE folders SET watch = ? WHERE id = ?", (1 if watch else 0, folder_id))
        self._conn.commit()

    def set_folder_auto_lookup(self, folder_id: int, auto_lookup: bool) -> None:
        self._conn.execute("UPDATE folders SET auto_lookup = ? WHERE id = ?", (1 if auto_lookup else 0, folder_id))
        self._conn.commit()

    def get_folder_id(self, path: str) -> int | None:
        row = self._conn.execute("SELECT id FROM folders WHERE path = ?", (path,)).fetchone()
        return row["id"] if row else None

    def get_folder_books_indexed(self, folder_id: int) -> dict[str, dict]:
        rows = self._conn.execute(
            "SELECT path, size_bytes, file_mtime FROM books WHERE folder_id = ? AND source = 'local'",
            (folder_id,)
        ).fetchall()
        return {r["path"]: {"size_bytes": r["size_bytes"], "file_mtime": r["file_mtime"]} for r in rows}

    def add_drive_account(
        self,
        email: str,
        display_name: str | None = None,
        provider: str = "gdrive",
        status: str | None = None,
        state: str = "ok",
        **kwargs: Any,
    ) -> int:
        acct_state = status or state or "ok"
        cur = self._conn.execute(
            "INSERT INTO drive_accounts (email, display_name, provider, state) VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET display_name = excluded.display_name, state = excluded.state, provider = excluded.provider",
            (email, display_name, provider, acct_state),
        )
        self._conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = self._conn.execute("SELECT id FROM drive_accounts WHERE email = ?", (email,)).fetchone()
        return row[0]

    upsert_drive_account = add_drive_account

    def list_drive_accounts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, email, display_name, provider, changes_token, state, added_at, last_sync_at FROM drive_accounts ORDER BY email"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_drive_account(self, account_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, email, display_name, provider, changes_token, state, added_at, last_sync_at FROM drive_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        return dict(row) if row else None

    def add_drive_folder(
        self,
        account_id: int,
        drive_folder_id: str,
        display_name: str | None = None,
        folder_name: str | None = None,
        include_subfolders: bool = True,
        deep_index: bool = False,
        sync_enabled: bool = True,
        sync_auto: bool | None = None,
        **kwargs: Any,
    ) -> int:
        if sync_auto is not None:
            sync_enabled = sync_auto
        name = display_name or folder_name or drive_folder_id
        vpath = f"gdrive://{account_id}/{drive_folder_id}"
        cur = self._conn.execute(
            """INSERT INTO folders (path, kind, account_id, drive_folder_id, drive_display, include_subfolders, deep_index, sync_enabled)
               VALUES (?, 'drive', ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET drive_display = excluded.drive_display, sync_enabled = excluded.sync_enabled""",
            (vpath, account_id, drive_folder_id, name, 1 if include_subfolders else 0, 1 if deep_index else 0, 1 if sync_enabled else 0),
        )
        self._conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = self._conn.execute("SELECT id FROM folders WHERE path = ?", (vpath,)).fetchone()
        return row[0]

    def update_drive_folder_sync_token(self, folder_id: int, token: str) -> None:
        self._conn.execute(
            """UPDATE drive_accounts SET changes_token = ?
               WHERE id = (SELECT account_id FROM folders WHERE id = ?)""",
            (token, folder_id)
        )
        self._conn.commit()

    def get_drive_folder_sync_token(self, folder_id: int) -> str | None:
        row = self._conn.execute(
            """SELECT changes_token FROM drive_accounts
               WHERE id = (SELECT account_id FROM folders WHERE id = ?)""",
            (folder_id,)
        ).fetchone()
        return row[0] if row else None

    def set_cached_file(self, book_id: int, file_path: str, size_bytes: int, md5: str | None = None) -> None:
        self._conn.execute(
            """INSERT INTO drive_cache (book_id, file_path, size_bytes, md5, downloaded_at, last_used_at, last_opened_at)
               VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
               ON CONFLICT(book_id) DO UPDATE SET
                   file_path = excluded.file_path,
                   size_bytes = excluded.size_bytes,
                   md5 = excluded.md5,
                   last_used_at = datetime('now'),
                   last_opened_at = datetime('now')""",
            (book_id, file_path, size_bytes, md5)
        )
        self._conn.commit()

    def get_cached_file(self, book_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT book_id, file_path, size_bytes, md5, downloaded_at, last_used_at, in_use_until FROM drive_cache WHERE book_id = ?",
            (book_id,)
        ).fetchone()
        return dict(row) if row else None

    def remove_cached_file(self, book_id: int) -> None:
        self._conn.execute("DELETE FROM drive_cache WHERE book_id = ?", (book_id,))
        self._conn.commit()

    def list_drive_folders(self, account_id: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id, path, kind, account_id, drive_folder_id, drive_display, include_subfolders, deep_index, sync_enabled, last_scanned_at FROM folders WHERE kind = 'drive'"
        params = []
        if account_id is not None:
            sql += " AND account_id = ?"
            params.append(account_id)
        sql += " ORDER BY drive_display"
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_app_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_app_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)", (key, value))
        self._conn.commit()

    # ── Books – write ─────────────────────────────────────────────────────────

    def upsert_book(self, *, folder_id: int, path: str, filename: str,
                    format: str, size_bytes: int, file_mtime: float,
                    title: str | None = None, author: str | None = None, publisher: str | None = None,
                    year: int | None = None, isbn: str | None = None, pages: int | None = None,
                    genre: str | None = None, language: str | None = None,
                    cover_path: str | None = None, quick_hash: str | None = None,
                    series_name: str | None = None, series_index: float | None = None,
                    source: str = "local", drive_file_id: str | None = None,
                    md5: str | None = None, drive_path: str | None = None,
                    drive_web_link: str | None = None, index_level: str = "full",
                    keep_offline: int | bool = 0, status: str | None = None,
                    commit: bool = True) -> int:
        """Insert or update a book, respecting field_sources / edited_fields on UPDATE."""
        existing = self._conn.execute(
            "SELECT id, edited_fields, field_sources, cover_source FROM books WHERE path = ?", (path,)
        ).fetchone()

        series_id = self.get_or_create_series(series_name) if series_name else None

        if existing:
            # Parse field_sources or fallback to edited_fields
            sources: dict[str, str] = {}
            if existing["field_sources"]:
                try:
                    sources = json.loads(existing["field_sources"])
                except Exception:
                    pass
            elif existing["edited_fields"]:
                try:
                    edited = json.loads(existing["edited_fields"] or "[]")
                    sources = {f: "manual" for f in edited}
                except Exception:
                    pass

            meta_fields = {
                "title": title, "author": author, "publisher": publisher,
                "year": year, "isbn": isbn, "pages": pages,
                "genre": genre, "language": language,
            }
            set_parts = [
                "folder_id = :folder_id", "filename = :filename", "format = :format",
                "size_bytes = :size_bytes", "file_mtime = :file_mtime", "is_missing = 0",
            ]
            params: dict = dict(
                folder_id=folder_id, filename=filename, format=format,
                size_bytes=size_bytes, file_mtime=file_mtime,
                path=path,
            )

            if source:
                set_parts.append("source = :source")
                params["source"] = source
            if drive_file_id is not None:
                set_parts.append("drive_file_id = :drive_file_id")
                params["drive_file_id"] = drive_file_id
            if md5 is not None:
                set_parts.append("md5 = :md5")
                params["md5"] = md5
            if drive_path is not None:
                set_parts.append("drive_path = :drive_path")
                params["drive_path"] = drive_path
            if drive_web_link is not None:
                set_parts.append("drive_web_link = :drive_web_link")
                params["drive_web_link"] = drive_web_link
            if index_level:
                set_parts.append("index_level = :index_level")
                params["index_level"] = index_level
            if keep_offline is not None:
                set_parts.append("keep_offline = :keep_offline")
                params["keep_offline"] = 1 if keep_offline else 0
            if status is not None:
                set_parts.append("status = :status")
                params["status"] = status

            # Only overwrite cover_path if it's provided and cover_source is file/placeholder
            if cover_path is not None and existing["cover_source"] in ("file", "placeholder", None):
                set_parts.append("cover_path = :cover_path")
                params["cover_path"] = cover_path

            if quick_hash is not None:
                set_parts.append("quick_hash = :quick_hash")
                params["quick_hash"] = quick_hash

            if series_id is not None and "series" not in sources:
                set_parts.append("series_id = :series_id")
                params["series_id"] = series_id
            if series_index is not None and "series_index" not in sources:
                set_parts.append("series_index = :series_index")
                params["series_index"] = series_index

            for field_name, val in meta_fields.items():
                # Only overwrite fields that were not manually edited
                if sources.get(field_name) != "manual":
                    set_parts.append(f"{field_name} = :{field_name}")
                    params[field_name] = val
                    if val is not None:
                        sources[field_name] = "file"

            set_parts.append("field_sources = :field_sources")
            params["field_sources"] = json.dumps(sources)

            self._conn.execute(
                f"UPDATE books SET {', '.join(set_parts)} WHERE path = :path", params
            )
            if commit:
                self._conn.commit()
            return existing["id"]
        else:
            cover_src = "placeholder" if format in ("mobi", "azw3", "djvu", "txt") else "file"
            sources = {k: "file" for k, v in [
                ("title", title), ("author", author), ("publisher", publisher),
                ("year", year), ("isbn", isbn), ("pages", pages),
                ("genre", genre), ("language", language),
            ] if v is not None}

            cur = self._conn.execute(
                """
                INSERT INTO books
                    (folder_id, path, filename, format, size_bytes, file_mtime,
                     title, author, publisher, year, isbn, pages, genre, language,
                     cover_path, cover_source, quick_hash, series_id, series_index,
                     field_sources, is_missing, source, drive_file_id, md5,
                     drive_path, drive_web_link, index_level, keep_offline, status)
                VALUES
                    (:folder_id, :path, :filename, :format, :size_bytes, :file_mtime,
                     :title, :author, :publisher, :year, :isbn, :pages, :genre, :language,
                     :cover_path, :cover_source, :quick_hash, :series_id, :series_index,
                     :field_sources, 0, :source, :drive_file_id, :md5,
                     :drive_path, :drive_web_link, :index_level, :keep_offline, :status)
                """,
                dict(folder_id=folder_id, path=path, filename=filename,
                     format=format, size_bytes=size_bytes, file_mtime=file_mtime,
                     title=title, author=author, publisher=publisher,
                     year=year, isbn=isbn, pages=pages, genre=genre,
                     language=language, cover_path=cover_path, cover_source=cover_src,
                     quick_hash=quick_hash, series_id=series_id, series_index=series_index,
                     field_sources=json.dumps(sources),
                     source=source, drive_file_id=drive_file_id, md5=md5,
                     drive_path=drive_path, drive_web_link=drive_web_link,
                     index_level=index_level, keep_offline=1 if keep_offline else 0,
                     status=status),
            )
            if commit:
                self._conn.commit()
            return cur.lastrowid

    def update_cover(self, book_id: int, cover_path: str | None, cover_source: str = "file") -> None:
        self._conn.execute(
            "UPDATE books SET cover_path = ?, cover_source = ? WHERE id = ?",
            (cover_path, cover_source, book_id),
        )

    def mark_missing(self, paths: list[str]) -> None:
        if not paths:
            return
        placeholders = ",".join("?" * len(paths))
        self._conn.execute(
            f"UPDATE books SET is_missing = 1 WHERE path IN ({placeholders})", paths
        )

    def count_missing(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM books WHERE is_missing = 1").fetchone()
        return row[0] if row else 0

    def mark_present(self, paths: list[str]) -> None:
        if not paths:
            return
        placeholders = ",".join("?" * len(paths))
        self._conn.execute(
            f"UPDATE books SET is_missing = 0 WHERE path IN ({placeholders})", paths
        )

    def remove_missing(self) -> int:
        cur = self._conn.execute("DELETE FROM books WHERE is_missing = 1")
        self._conn.commit()
        return cur.rowcount

    def commit(self) -> None:
        self._conn.commit()

    # ── Books – read ──────────────────────────────────────────────────────────

    def query_books(self, q: LibraryQuery) -> list[BookRow]:
        """Build and execute one SQL statement from a LibraryQuery."""
        clauses: list[str] = []
        params: list = []

        if not q.include_missing:
            clauses.append("b.is_missing = 0")

        # Search (FTS or LIKE fallback)
        if q.search:
            fts_expr = build_fts_query(q.search)
            if fts_expr:
                if self._use_fts:
                    clauses.append("b.id IN (SELECT rowid FROM books_fts WHERE books_fts MATCH ?)")
                    params.append(fts_expr)
                else:
                    like = f"%{q.search}%"
                    clauses.append(
                        "(b.title LIKE ? OR b.author LIKE ? OR b.publisher LIKE ? "
                        "OR b.genre LIKE ? OR b.isbn LIKE ? OR b.notes LIKE ? OR b.filename LIKE ? OR b.tags_text LIKE ?)"
                    )
                    params.extend([like] * 8)

        # Shelf shortcuts
        if q.shelf == "continue":
            clauses.append("b.status = 'reading'")
        elif q.shelf == "recent":
            clauses.append("b.date_added >= datetime('now', '-30 days')")
        elif q.shelf == "needs_review":
            clauses.append("b.lookup_status = 'review'")
        elif q.shelf == "incomplete":
            clauses.append("(b.title IS NULL OR b.author IS NULL OR b.year IS NULL OR b.cover_source = 'placeholder')")

        # Incomplete flag
        if q.incomplete:
            clauses.append("(b.title IS NULL OR b.author IS NULL OR b.year IS NULL OR b.cover_source = 'placeholder')")

        # Status filter
        if q.statuses and not q.shelf:
            parts: list[str] = []
            for s in q.statuses:
                if s == "none":
                    parts.append("b.status IS NULL")
                else:
                    parts.append("b.status = ?")
                    params.append(s)
            clauses.append(f"({' OR '.join(parts)})")

        # Formats
        if q.formats:
            placeholders = ",".join("?" * len(q.formats))
            clauses.append(f"b.format IN ({placeholders})")
            params.extend(q.formats)

        # Authors
        if q.authors:
            placeholders = ",".join("?" * len(q.authors))
            clauses.append(f"b.author IN ({placeholders})")
            params.extend(q.authors)

        # Genres
        if q.genres:
            placeholders = ",".join("?" * len(q.genres))
            clauses.append(f"b.genre IN ({placeholders})")
            params.extend(q.genres)

        # Languages
        if q.languages:
            placeholders = ",".join("?" * len(q.languages))
            clauses.append(f"b.language IN ({placeholders})")
            params.extend(q.languages)

        # Rating
        if q.min_rating is not None:
            clauses.append("b.rating >= ?")
            params.append(q.min_rating)

        # Series filter
        if q.series_id is not None:
            clauses.append("b.series_id = ?")
            params.append(q.series_id)

        # Collection filter
        if q.collection_id is not None:
            clauses.append("b.id IN (SELECT book_id FROM collection_books WHERE collection_id = ?)")
            params.append(q.collection_id)

        # Lookup status
        if q.lookup_status is not None:
            clauses.append("b.lookup_status = ?")
            params.append(q.lookup_status)

        # Sources filter (v4)
        if q.sources:
            expanded_sources = set(q.sources)
            if "gdrive" in expanded_sources or "drive" in expanded_sources:
                expanded_sources.add("gdrive")
                expanded_sources.add("drive")
            placeholders = ",".join("?" * len(expanded_sources))
            clauses.append(f"b.source IN ({placeholders})")
            params.extend(list(expanded_sources))

        # Offline only filter (v4)
        if q.offline_only:
            clauses.append("(b.source = 'local' OR dc.file_path IS NOT NULL OR b.keep_offline = 1)")

        # Drive folder filter (v4)
        if q.drive_folder_id is not None:
            clauses.append("b.folder_id = ?")
            params.append(q.drive_folder_id)

        # Specific book_ids filter (v6)
        if q.book_ids:
            placeholders = ",".join("?" * len(q.book_ids))
            clauses.append(f"b.id IN ({placeholders})")
            params.extend(q.book_ids)

        # Tags filter
        if q.tag_ids:
            placeholders = ",".join("?" * len(q.tag_ids))
            if q.tag_mode == "all":
                clauses.append(
                    f"b.id IN (SELECT book_id FROM book_tags WHERE tag_id IN ({placeholders}) "
                    f"GROUP BY book_id HAVING COUNT(DISTINCT tag_id) = {len(q.tag_ids)})"
                )
                params.extend(q.tag_ids)
            else:
                clauses.append(f"b.id IN (SELECT book_id FROM book_tags WHERE tag_id IN ({placeholders}))")
                params.extend(q.tag_ids)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        # ── ORDER BY ──────────────────────────────────────────────────────────
        sort_field = q.sort_field if q.sort_field in VALID_SORT_FIELDS else "title"
        direction = "DESC" if q.sort_desc else "ASC"

        TEXT_SORT_FIELDS = {"title", "author", "format", "publisher", "genre", "language", "source"}
        collate_clause = 'COLLATE "NATURAL"' if sort_field in TEXT_SORT_FIELDS else ""

        if q.sort_field == "series":
            order = (
                f'ORDER BY (s.name IS NULL), s.name COLLATE "NATURAL" {direction}, '
                f"(b.series_index IS NULL), b.series_index ASC, b.title COLLATE \"NATURAL\" ASC"
            )
        elif q.sort_field == "progress":
            order = (
                f"ORDER BY (b.progress_percent IS NULL), b.progress_percent {direction}, "
                f'b.title COLLATE "NATURAL" ASC'
            )
        elif q.sort_field == "source":
            order = f"ORDER BY b.source {direction}, b.title COLLATE \"NATURAL\" ASC"
        elif q.shelf == "continue":
            order = 'ORDER BY (b.last_opened_at IS NULL), b.last_opened_at DESC, b.title COLLATE "NATURAL" ASC'
        elif q.shelf == "recent":
            order = "ORDER BY b.date_added DESC"
        else:
            order = (
                f"ORDER BY (b.{sort_field} IS NULL), "
                f"b.{sort_field} {collate_clause} {direction}, "
                f'b.title COLLATE "NATURAL" ASC'
            )

        sql = f"""
            SELECT b.id, b.title, b.author, b.year, b.size_bytes, b.format,
                   b.pages, b.cover_path, b.date_added, b.is_missing, b.path,
                   b.status, b.rating, b.last_opened_at, b.open_count,
                   b.publisher, b.genre, b.language, b.isbn, b.edition,
                   b.field_sources, b.description, b.cover_source,
                   b.series_id, s.name as series_name, b.series_index,
                   b.progress_page, b.progress_percent, b.lookup_status, b.tags_text,
                   b.source, b.drive_file_id, b.md5, b.drive_path, b.drive_web_link,
                   b.index_level, b.keep_offline, dc.file_path as cached_path
            FROM books b
            LEFT JOIN series s ON b.series_id = s.id
            LEFT JOIN drive_cache dc ON b.id = dc.book_id
            {where}
            {order}
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [
            BookRow(
                id=r["id"], title=r["title"], author=r["author"],
                year=r["year"], size_bytes=r["size_bytes"], format=r["format"],
                pages=r["pages"], cover_path=r["cover_path"],
                date_added=r["date_added"], is_missing=bool(r["is_missing"]),
                path=r["path"], status=r["status"], rating=r["rating"],
                last_opened_at=r["last_opened_at"], open_count=r["open_count"] or 0,
                publisher=r["publisher"], genre=r["genre"],
                language=r["language"], isbn=r["isbn"], edition=r["edition"],
                field_sources=json.loads(r["field_sources"] or "{}"),
                description=r["description"], cover_source=r["cover_source"] or "file",
                series_id=r["series_id"], series_name=r["series_name"],
                series_index=r["series_index"],
                progress_page=r["progress_page"], progress_percent=r["progress_percent"],
                lookup_status=r["lookup_status"], tags_text=r["tags_text"],
                source=r["source"] or "local", drive_file_id=r["drive_file_id"],
                md5=r["md5"], drive_path=r["drive_path"],
                drive_web_link=r["drive_web_link"], index_level=r["index_level"] or "full",
                keep_offline=bool(r["keep_offline"]),
                is_cached=bool(r["cached_path"]), cached_path=r["cached_path"],
            )
            for r in rows
        ]

    def list_books(self, sort_field: str = "title", ascending: bool = True,
                   include_missing: bool = False) -> list[BookRow]:
        q = LibraryQuery(sort_field=sort_field, sort_desc=not ascending,
                         include_missing=include_missing)
        return self.query_books(q)

    def get_book_row(self, book_id: int) -> BookRow | None:
        """Fetch a single BookRow by ID, including missing books."""
        sql = """
            SELECT b.id, b.title, b.author, b.year, b.size_bytes, b.format,
                   b.pages, b.cover_path, b.date_added, b.is_missing, b.path,
                   b.status, b.rating, b.last_opened_at, b.open_count,
                   b.publisher, b.genre, b.language, b.isbn, b.edition,
                   b.field_sources, b.description, b.cover_source,
                   b.series_id, s.name as series_name, b.series_index,
                   b.progress_page, b.progress_percent, b.lookup_status, b.tags_text,
                   b.source, b.drive_file_id, b.md5, b.drive_path, b.drive_web_link,
                   b.index_level, b.keep_offline, dc.file_path as cached_path
            FROM books b
            LEFT JOIN series s ON b.series_id = s.id
            LEFT JOIN drive_cache dc ON b.id = dc.book_id
            WHERE b.id = ?
        """
        r = self._conn.execute(sql, (book_id,)).fetchone()
        if r is None:
            return None
        return BookRow(
            id=r["id"], title=r["title"], author=r["author"],
            year=r["year"], size_bytes=r["size_bytes"], format=r["format"],
            pages=r["pages"], cover_path=r["cover_path"],
            date_added=r["date_added"], is_missing=bool(r["is_missing"]),
            path=r["path"], status=r["status"], rating=r["rating"],
            last_opened_at=r["last_opened_at"], open_count=r["open_count"] or 0,
            publisher=r["publisher"], genre=r["genre"],
            language=r["language"], isbn=r["isbn"], edition=r["edition"],
            field_sources=json.loads(r["field_sources"] or "{}"),
            description=r["description"], cover_source=r["cover_source"] or "file",
            series_id=r["series_id"], series_name=r["series_name"],
            series_index=r["series_index"],
            progress_page=r["progress_page"], progress_percent=r["progress_percent"],
            lookup_status=r["lookup_status"], tags_text=r["tags_text"],
            source=r["source"] or "local", drive_file_id=r["drive_file_id"],
            md5=r["md5"], drive_path=r["drive_path"],
            drive_web_link=r["drive_web_link"], index_level=r["index_level"] or "full",
            keep_offline=bool(r["keep_offline"]),
            is_cached=bool(r["cached_path"]), cached_path=r["cached_path"],
        )

    def get_book_detail(self, book_id: int) -> BookDetail | None:
        row = self._conn.execute(
            """
            SELECT b.id, b.title, b.author, b.publisher, b.year, b.edition, b.isbn, b.pages,
                   b.genre, b.language, b.size_bytes, b.format, b.path, b.cover_path,
                   b.date_added, b.is_missing, b.status, b.rating, b.notes,
                   b.last_opened_at, b.open_count, b.edited_fields,
                   b.field_sources, b.description, b.online_source, b.online_id,
                   b.lookup_status, b.lookup_at, b.cover_source, b.quick_hash, b.file_hash,
                   b.series_id, s.name as series_name, b.series_index,
                   b.progress_page, b.progress_percent,
                   b.source, b.drive_file_id, b.md5, b.drive_path, b.drive_web_link,
                   b.index_level, b.keep_offline, dc.file_path as cached_path
            FROM books b
            LEFT JOIN series s ON b.series_id = s.id
            LEFT JOIN drive_cache dc ON b.id = dc.book_id
            WHERE b.id = ?
            """,
            (book_id,),
        ).fetchone()
        if row is None:
            return None

        # Tags
        tags = self.get_book_tags(book_id)

        # Collections
        colls = self._conn.execute(
            """
            SELECT c.id, c.name, c.kind
            FROM collections c
            JOIN collection_books cb ON c.id = cb.collection_id
            WHERE cb.book_id = ?
            ORDER BY c.sort_order, c.name
            """,
            (book_id,)
        ).fetchall()

        # Reading log
        log_rows = self.get_reading_log(book_id)

        field_sources = json.loads(row["field_sources"] or "{}")
        edited_fields = json.loads(row["edited_fields"] or "[]")
        if not edited_fields and field_sources:
            edited_fields = [k for k, v in field_sources.items() if v == "manual"]

        return BookDetail(
            id=row["id"], title=row["title"], author=row["author"],
            publisher=row["publisher"], year=row["year"], edition=row["edition"],
            isbn=row["isbn"], pages=row["pages"], genre=row["genre"],
            language=row["language"], size_bytes=row["size_bytes"],
            format=row["format"], path=row["path"], cover_path=row["cover_path"],
            date_added=row["date_added"], is_missing=bool(row["is_missing"]),
            status=row["status"], rating=row["rating"], notes=row["notes"],
            last_opened_at=row["last_opened_at"], open_count=row["open_count"] or 0,
            edited_fields=edited_fields,
            field_sources=field_sources,
            description=row["description"],
            online_source=row["online_source"],
            online_id=row["online_id"],
            lookup_status=row["lookup_status"],
            lookup_at=row["lookup_at"],
            cover_source=row["cover_source"] or "file",
            quick_hash=row["quick_hash"],
            file_hash=row["file_hash"],
            series_id=row["series_id"],
            series_name=row["series_name"],
            series_index=row["series_index"],
            progress_page=row["progress_page"],
            progress_percent=row["progress_percent"],
            source=row["source"] or "local",
            drive_file_id=row["drive_file_id"],
            md5=row["md5"],
            drive_path=row["drive_path"],
            drive_web_link=row["drive_web_link"],
            index_level=row["index_level"] or "full",
            keep_offline=bool(row["keep_offline"]),
            is_cached=bool(row["cached_path"]),
            cached_path=row["cached_path"],
            tags=tags,
            collections=[dict(c) for c in colls],
            reading_log=log_rows,
        )

    def get_book_by_path(self, path: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM books WHERE path = ?", (path,)).fetchone()
        return dict(row) if row else None

    def count_books(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM books WHERE is_missing = 0"
        ).fetchone()[0]

    def count_by_status(self) -> dict[str, int]:
        """Return {status_key: count} for sidebar display."""
        rows = self._conn.execute(
            """
            SELECT COALESCE(status, 'none') as s, COUNT(*) as c
            FROM books WHERE is_missing = 0
            GROUP BY s
            """
        ).fetchall()
        result = {"want": 0, "reading": 0, "read": 0, "none": 0}
        for r in rows:
            result[r["s"]] = r["c"]
        result["all"] = sum(result.values())
        result["continue"] = result["reading"]
        result["recent"] = self._conn.execute(
            "SELECT COUNT(*) FROM books WHERE is_missing=0 AND date_added >= datetime('now','-30 days')"
        ).fetchone()[0]
        result["needs_review"] = self._conn.execute(
            "SELECT COUNT(*) FROM books WHERE is_missing=0 AND lookup_status = 'review'"
        ).fetchone()[0]
        result["incomplete"] = self._conn.execute(
            "SELECT COUNT(*) FROM books WHERE is_missing=0 AND (title IS NULL OR author IS NULL OR year IS NULL OR cover_source = 'placeholder')"
        ).fetchone()[0]
        result["gdrive"] = self._conn.execute(
            "SELECT COUNT(*) FROM books WHERE is_missing = 0 AND (source = 'gdrive' OR source = 'drive')"
        ).fetchone()[0]
        result["local"] = self._conn.execute(
            "SELECT COUNT(*) FROM books WHERE is_missing = 0 AND source = 'local'"
        ).fetchone()[0]
        try:
            result["offline"] = self._conn.execute(
                """SELECT COUNT(DISTINCT b.id) FROM books b
                   JOIN drive_cache c ON b.id = c.book_id
                   WHERE b.is_missing = 0"""
            ).fetchone()[0]
        except Exception:
            result["offline"] = 0
        return result

    def facet_counts(self, field: str, q: LibraryQuery) -> list[tuple[str, int]]:
        allowed = {"format", "author", "genre", "language"}
        if field not in allowed:
            return []
        rows = self._conn.execute(
            f"""
            SELECT {field}, COUNT(*) as c FROM books
            WHERE is_missing = 0 AND {field} IS NOT NULL
            GROUP BY {field} ORDER BY c DESC, {field} COLLATE NOCASE
            LIMIT 100
            """
        ).fetchall()
        return [(r[field], r["c"]) for r in rows]

    # ── Status and Reading Log ────────────────────────────────────────────────

    def set_status(self, book_ids: list[int], status: str | None) -> None:
        """Set status for one or more books and update reading_log accordingly."""
        if status is not None and status not in ("want", "reading", "read"):
            raise ValueError(f"Invalid status: {status!r}")
        if not book_ids:
            return

        today = datetime.now().strftime("%Y-%m-%d")
        placeholders = ",".join("?" * len(book_ids))

        self._conn.execute(
            f"""
            UPDATE books SET status = ?, status_changed_at = datetime('now')
            WHERE id IN ({placeholders})
            """,
            [status, *book_ids],
        )

        for bid in book_ids:
            if status == "reading":
                # Check for active reading (finished_on IS NULL)
                active = self._conn.execute(
                    "SELECT id FROM reading_log WHERE book_id = ? AND finished_on IS NULL", (bid,)
                ).fetchone()
                if not active:
                    self._conn.execute(
                        "INSERT INTO reading_log (book_id, started_on) VALUES (?, ?)", (bid, today)
                    )
            elif status == "read":
                # Close active reading or insert completed entry
                active = self._conn.execute(
                    "SELECT id FROM reading_log WHERE book_id = ? AND finished_on IS NULL", (bid,)
                ).fetchone()
                if active:
                    self._conn.execute(
                        "UPDATE reading_log SET finished_on = ? WHERE id = ?", (today, active["id"])
                    )
                else:
                    self._conn.execute(
                        "INSERT INTO reading_log (book_id, finished_on) VALUES (?, ?)", (bid, today)
                    )
                # Clear progress on read
                self._conn.execute(
                    "UPDATE books SET progress_page = NULL, progress_percent = 100.0 WHERE id = ?", (bid,)
                )

        self._conn.commit()

    def read_again(self, book_id: int) -> None:
        """Mark a book to be read again: sets reading status and starts a new reading_log entry."""
        today = datetime.now().strftime("%Y-%m-%d")
        self._conn.execute(
            "UPDATE books SET status = 'reading', status_changed_at = datetime('now'), progress_page = NULL, progress_percent = 0.0 WHERE id = ?",
            (book_id,),
        )
        self._conn.execute(
            "INSERT INTO reading_log (book_id, started_on) VALUES (?, ?)", (book_id, today)
        )
        self._conn.commit()

    def get_reading_log(self, book_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, book_id, started_on, finished_on, note FROM reading_log WHERE book_id = ? ORDER BY id DESC",
            (book_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def add_reading_log_entry(self, book_id: int, started_on: str | None, finished_on: str | None, note: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO reading_log (book_id, started_on, finished_on, note) VALUES (?, ?, ?, ?)",
            (book_id, started_on, finished_on, note),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_reading_log_entry(self, entry_id: int, started_on: str | None, finished_on: str | None, note: str | None = None) -> None:
        self._conn.execute(
            "UPDATE reading_log SET started_on = ?, finished_on = ?, note = ? WHERE id = ?",
            (started_on, finished_on, note, entry_id),
        )
        self._conn.commit()

    def delete_reading_log_entry(self, entry_id: int) -> None:
        self._conn.execute("DELETE FROM reading_log WHERE id = ?", (entry_id,))
        self._conn.commit()

    def set_progress(self, book_id: int, page: int | None, percent: float | None) -> None:
        self._conn.execute(
            "UPDATE books SET progress_page = ?, progress_percent = ? WHERE id = ?",
            (page, percent, book_id),
        )
        self._conn.commit()

    def record_open(self, book_id: int) -> None:
        self._conn.execute(
            """
            UPDATE books
            SET last_opened_at = datetime('now'),
                open_count = open_count + 1
            WHERE id = ?
            """,
            (book_id,),
        )
        self._conn.commit()

    def set_rating(self, book_id: int, rating: int | None) -> None:
        if rating is not None and not (1 <= rating <= 5):
            raise ValueError(f"Rating must be 1–5 or None, got {rating}")
        self._conn.execute("UPDATE books SET rating = ? WHERE id = ?", (rating, book_id))
        self._conn.commit()

    def set_notes(self, book_id: int, notes: str) -> None:
        self._conn.execute(
            "UPDATE books SET notes = ? WHERE id = ?",
            (notes or None, book_id),
        )
        self._conn.commit()

    # ── Metadata Editing & Field Provenance ───────────────────────────────────

    def edit_book(self, book_id: int, fields: dict[str, Any]) -> None:
        """Apply manual metadata changes and tag field_sources[k] = 'manual'."""
        row = self._conn.execute(
            "SELECT field_sources FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        sources: dict[str, str] = json.loads(row["field_sources"] or "{}") if row else {}

        EDITABLE = {"title", "author", "publisher", "year", "edition",
                    "isbn", "pages", "genre", "language", "description"}
        update_parts: list[str] = []
        params: list = []
        for col, val in fields.items():
            if col in EDITABLE:
                update_parts.append(f"{col} = ?")
                params.append(val)
                if val is not None:
                    sources[col] = "manual"

        if not update_parts:
            return

        update_parts.append("field_sources = ?")
        params.append(json.dumps(sources))
        update_parts.append("edited_fields = ?")
        params.append(json.dumps(sorted([k for k, v in sources.items() if v == "manual"])))

        params.append(book_id)
        self._conn.execute(
            f"UPDATE books SET {', '.join(update_parts)} WHERE id = ?", params
        )
        self._conn.commit()

    def bulk_edit_books(self, book_ids: list[int], fields: dict[str, Any]) -> None:
        for book_id in book_ids:
            self.edit_book(book_id, fields)

    def revert_book(self, book_id: int, meta: dict) -> None:
        """Overwrite metadata with file extractor values and clear manual marks."""
        sources = {k: "file" for k, v in meta.items() if v is not None}
        self._conn.execute(
            """
            UPDATE books SET
                title=:title, author=:author, publisher=:publisher,
                year=:year, isbn=:isbn, pages=:pages, genre=:genre,
                language=:language, description=NULL, field_sources=:sources,
                edited_fields=NULL
            WHERE id=:id
            """,
            {**meta, "sources": json.dumps(sources), "id": book_id},
        )
        self._conn.commit()

    # ── Online Lookup History & Batch Undo ────────────────────────────────────

    def apply_online_metadata(
        self,
        book_id: int,
        fields: dict[str, Any],
        provider: str,
        provider_id: str | None = None,
        batch_id: str | None = None,
        replace_file: bool = False,
    ) -> str:
        """
        Apply fetched online candidate fields.
        Respects 'manual' provenance (never overwrites).
        Writes to metadata_history for undo.
        Returns the batch_id.
        """
        import uuid
        batch_id = batch_id or str(uuid.uuid4())
        detail = self.get_book_detail(book_id)
        if not detail:
            return batch_id

        sources = dict(detail.field_sources)
        before_snapshot: dict[str, Any] = {}
        after_snapshot: dict[str, Any] = {}
        update_parts: list[str] = []
        params: list = []

        for field_name, new_val in fields.items():
            if new_val is None or new_val == "":
                continue
            curr_src = sources.get(field_name, "file")
            # Rule: NEVER overwrite manual fields
            if curr_src == "manual":
                continue
            curr_val = getattr(detail, field_name, None)
            # If fill-only mode, only fill empty fields
            if not replace_file and curr_val not in (None, ""):
                continue

            before_snapshot[field_name] = curr_val
            after_snapshot[field_name] = new_val
            update_parts.append(f"{field_name} = ?")
            params.append(new_val)
            sources[field_name] = f"online:{provider}"

        if after_snapshot:
            # Record metadata_history row
            self._conn.execute(
                """
                INSERT INTO metadata_history (batch_id, book_id, source, before_json, after_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (batch_id, book_id, f"online:{provider}", json.dumps(before_snapshot), json.dumps(after_snapshot)),
            )

            update_parts.append("field_sources = ?")
            params.append(json.dumps(sources))
            update_parts.append("online_source = ?")
            params.append(provider)
            if provider_id:
                update_parts.append("online_id = ?")
                params.append(provider_id)
            update_parts.append("lookup_status = 'applied'")
            update_parts.append("lookup_at = datetime('now')")

            params.append(book_id)
            self._conn.execute(
                f"UPDATE books SET {', '.join(update_parts)} WHERE id = ?", params
            )
            self._conn.commit()
        else:
            self._conn.execute(
                "UPDATE books SET lookup_status = 'applied', lookup_at = datetime('now') WHERE id = ?",
                (book_id,)
            )
            self._conn.commit()

        return batch_id

    def undo_metadata_batch(self, batch_id: str) -> int:
        """
        Undo a batch of online lookups.
        Restores before_json values ONLY if current values still equal after_json.
        """
        rows = self._conn.execute(
            "SELECT book_id, before_json, after_json FROM metadata_history WHERE batch_id = ?",
            (batch_id,)
        ).fetchall()

        restored_count = 0
        for r in rows:
            bid = r["book_id"]
            before_vals = json.loads(r["before_json"])
            after_vals = json.loads(r["after_json"])

            d = self.get_book_detail(bid)
            if not d:
                continue
            sources = dict(d.field_sources)
            set_parts = []
            params = []

            for k, expected_after in after_vals.items():
                curr_val = getattr(d, k, None)
                # Only restore if it hasn't been modified since
                if curr_val == expected_after:
                    old_v = before_vals.get(k)
                    set_parts.append(f"{k} = ?")
                    params.append(old_v)
                    if old_v is not None:
                        sources[k] = "file"
                    else:
                        sources.pop(k, None)

            if set_parts:
                set_parts.append("field_sources = ?")
                params.append(json.dumps(sources))
                set_parts.append("lookup_status = NULL")
                params.append(bid)
                self._conn.execute(f"UPDATE books SET {', '.join(set_parts)} WHERE id = ?", params)
                restored_count += 1

        self._conn.execute("DELETE FROM metadata_history WHERE batch_id = ?", (batch_id,))
        self._conn.commit()
        return restored_count

    def set_lookup_status(self, book_id: int, status: str | None) -> None:
        self._conn.execute(
            "UPDATE books SET lookup_status = ?, lookup_at = datetime('now') WHERE id = ?",
            (status, book_id),
        )
        self._conn.commit()

    def cache_online_response(self, cache_key: str, provider: str, response: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO online_cache (cache_key, provider, response, fetched_at) VALUES (?, ?, ?, datetime('now'))",
            (cache_key, provider, response),
        )
        self._conn.commit()

    def get_cached_online_response(self, cache_key: str, max_age_days: int = 30) -> str | None:
        row = self._conn.execute(
            f"SELECT response FROM online_cache WHERE cache_key = ? AND fetched_at >= datetime('now', '-{max_age_days} days')",
            (cache_key,)
        ).fetchone()
        return row["response"] if row else None

    # ── Tags ──────────────────────────────────────────────────────────────────

    def get_or_create_tag(self, name: str, color: str | None = None) -> int:
        clean = name.strip()[:40]
        row = self._conn.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean,)).fetchone()
        if row:
            return row["id"]
        cur = self._conn.execute("INSERT INTO tags (name, color) VALUES (?, ?)", (clean, color))
        self._conn.commit()
        return cur.lastrowid

    def create_tag(self, name: str, color: str | None = None) -> int:
        return self.get_or_create_tag(name, color)

    def add_tag_to_books(self, tag_name: str, book_ids: list[int]) -> int:
        tag_id = self.get_or_create_tag(tag_name)
        self.set_book_tags(book_ids, add_tag_ids=[tag_id], remove_tag_ids=[])
        return tag_id

    def remove_tag_from_books(self, tag_name_or_id: str | int, book_ids: list[int]) -> None:
        if isinstance(tag_name_or_id, str):
            row = self._conn.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (tag_name_or_id.strip(),)).fetchone()
            if not row:
                return
            tag_id = row["id"]
        else:
            tag_id = tag_name_or_id
        self.set_book_tags(book_ids, add_tag_ids=[], remove_tag_ids=[tag_id])

    def list_tags(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT t.id, t.name, t.color, COUNT(bt.book_id) as book_count
            FROM tags t
            LEFT JOIN book_tags bt ON t.id = bt.tag_id
            GROUP BY t.id
            ORDER BY t.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def rename_tag(self, tag_id: int, new_name: str) -> None:
        clean = new_name.strip()[:40]
        self._conn.execute("UPDATE tags SET name = ? WHERE id = ?", (clean, tag_id))
        self._conn.commit()
        self._rebuild_tags_text_for_tag(tag_id)

    def merge_tags(self, source_tag_id: int, target_tag_id: int) -> None:
        """Merge source tag into target tag and delete source."""
        # Find all books with source_tag
        rows = self._conn.execute("SELECT book_id FROM book_tags WHERE tag_id = ?", (source_tag_id,)).fetchall()
        for r in rows:
            self._conn.execute(
                "INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)",
                (r["book_id"], target_tag_id)
            )
        self.delete_tag(source_tag_id)

    def delete_tag(self, tag_id: int) -> None:
        # Find books that had this tag to rebuild their tags_text
        book_rows = self._conn.execute("SELECT book_id FROM book_tags WHERE tag_id = ?", (tag_id,)).fetchall()
        book_ids = [r["book_id"] for r in book_rows]
        self._conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        self._conn.commit()
        self._update_tags_text(book_ids)

    def set_book_tags(self, book_ids: list[int], add_tag_ids: list[int], remove_tag_ids: list[int]) -> None:
        for bid in book_ids:
            for tid in add_tag_ids:
                self._conn.execute("INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)", (bid, tid))
            for tid in remove_tag_ids:
                self._conn.execute("DELETE FROM book_tags WHERE book_id = ? AND tag_id = ?", (bid, tid))
        self._conn.commit()
        self._update_tags_text(book_ids)

    def get_book_tags(self, book_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT t.id, t.name, t.color
            FROM tags t
            JOIN book_tags bt ON t.id = bt.tag_id
            WHERE bt.book_id = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (book_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _update_tags_text(self, book_ids: list[int]) -> None:
        for bid in set(book_ids):
            tags = self.get_book_tags(bid)
            txt = " ".join(t["name"] for t in tags) if tags else None
            self._conn.execute("UPDATE books SET tags_text = ? WHERE id = ?", (txt, bid))
        self._conn.commit()

    def _rebuild_tags_text_for_tag(self, tag_id: int) -> None:
        rows = self._conn.execute("SELECT book_id FROM book_tags WHERE tag_id = ?", (tag_id,)).fetchall()
        self._update_tags_text([r["book_id"] for r in rows])

    # ── Collections ───────────────────────────────────────────────────────────

    def create_collection(self, name: str, kind: str = "manual", smart_query: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO collections (name, kind, smart_query) VALUES (?, ?, ?)",
            (name.strip(), kind, smart_query),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_collections(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT c.id, c.name, c.kind, c.smart_query, c.sort_order, COUNT(cb.book_id) as book_count
            FROM collections c
            LEFT JOIN collection_books cb ON c.id = cb.collection_id
            GROUP BY c.id
            ORDER BY c.sort_order, c.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def rename_collection(self, collection_id: int, new_name: str) -> None:
        self._conn.execute("UPDATE collections SET name = ? WHERE id = ?", (new_name.strip(), collection_id))
        self._conn.commit()

    def delete_collection(self, collection_id: int) -> None:
        self._conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        self._conn.commit()

    def add_books_to_collection(self, collection_id: int, book_ids: list[int]) -> None:
        for bid in book_ids:
            self._conn.execute(
                "INSERT OR IGNORE INTO collection_books (collection_id, book_id) VALUES (?, ?)",
                (collection_id, bid)
            )
        self._conn.commit()

    def remove_books_from_collection(self, collection_id: int, book_ids: list[int]) -> None:
        placeholders = ",".join("?" * len(book_ids))
        self._conn.execute(
            f"DELETE FROM collection_books WHERE collection_id = ? AND book_id IN ({placeholders})",
            [collection_id, *book_ids]
        )
        self._conn.commit()

    def reorder_collections(self, ordered_ids: list[int]) -> None:
        for order, cid in enumerate(ordered_ids):
            self._conn.execute("UPDATE collections SET sort_order = ? WHERE id = ?", (order, cid))
        self._conn.commit()

    # ── Series ────────────────────────────────────────────────────────────────

    def get_or_create_series(self, name: str | None) -> int | None:
        if not name or not name.strip():
            return None
        clean = name.strip()
        row = self._conn.execute("SELECT id FROM series WHERE name = ? COLLATE NOCASE", (clean,)).fetchone()
        if row:
            return row["id"]
        cur = self._conn.execute("INSERT INTO series (name) VALUES (?)", (clean,))
        self._conn.commit()
        return cur.lastrowid

    def list_series(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT s.id, s.name, COUNT(b.id) as book_count
            FROM series s
            JOIN books b ON s.id = b.series_id
            WHERE b.is_missing = 0
            GROUP BY s.id
            ORDER BY s.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def set_series(self, book_ids: list[int], series_name: str | None, index: float | None = None) -> None:
        series_id = self.get_or_create_series(series_name)
        for bid in book_ids:
            self._conn.execute(
                "UPDATE books SET series_id = ?, series_index = ? WHERE id = ?",
                (series_id, index, bid)
            )
        self._conn.commit()

    def bulk_number_series(self, book_ids: list[int], series_name: str, start_index: float = 1.0) -> None:
        series_id = self.get_or_create_series(series_name)
        for i, bid in enumerate(book_ids):
            self._conn.execute(
                "UPDATE books SET series_id = ?, series_index = ? WHERE id = ?",
                (series_id, start_index + i, bid)
            )
        self._conn.commit()

    def get_adjacent_series_books(self, book_id: int) -> tuple[int | None, int | None]:
        """Return (prev_book_id, next_book_id) within the same series."""
        detail = self.get_book_detail(book_id)
        if not detail or not detail.series_id or detail.series_index is None:
            return None, None

        prev_row = self._conn.execute(
            """
            SELECT id FROM books
            WHERE series_id = ? AND series_index < ? AND is_missing = 0
            ORDER BY series_index DESC, id DESC LIMIT 1
            """,
            (detail.series_id, detail.series_index)
        ).fetchone()

        next_row = self._conn.execute(
            """
            SELECT id FROM books
            WHERE series_id = ? AND series_index > ? AND is_missing = 0
            ORDER BY series_index ASC, id ASC LIMIT 1
            """,
            (detail.series_id, detail.series_index)
        ).fetchone()

        return (prev_row["id"] if prev_row else None, next_row["id"] if next_row else None)

    def get_series_neighbors(self, book_id: int, series_id: int | None = None) -> dict[str, int | None]:
        prev_id, next_id = self.get_adjacent_series_books(book_id)
        return {"prev_id": prev_id, "next_id": next_id}

    # ── Duplicates & Hashing ──────────────────────────────────────────────────

    def update_quick_hash(self, book_id: int, quick_hash: str) -> None:
        self._conn.execute("UPDATE books SET quick_hash = ? WHERE id = ?", (quick_hash, book_id))
        self._conn.commit()

    def update_file_hash(self, book_id: int, file_hash: str) -> None:
        self._conn.execute("UPDATE books SET file_hash = ? WHERE id = ?", (file_hash, book_id))
        self._conn.commit()

    def find_exact_duplicates(self) -> list[list[int]]:
        """Find groups of books with identical file_hash."""
        rows = self._conn.execute(
            """
            SELECT file_hash, GROUP_CONCAT(id) as ids
            FROM books
            WHERE is_missing = 0 AND file_hash IS NOT NULL
            GROUP BY file_hash
            HAVING COUNT(id) > 1
            """
        ).fetchall()
        groups = []
        for r in rows:
            ids = [int(x) for x in r["ids"].split(",")]
            key = f"exact:{':'.join(str(i) for i in sorted(ids))}"
            if not self.is_duplicate_group_ignored(key):
                groups.append(ids)
        return groups

    def find_isbn_duplicates(self) -> list[list[int]]:
        """Find books with same ISBN but different hashes."""
        rows = self._conn.execute(
            """
            SELECT isbn, GROUP_CONCAT(id) as ids
            FROM books
            WHERE is_missing = 0 AND isbn IS NOT NULL AND TRIM(isbn) != ''
            GROUP BY isbn
            HAVING COUNT(id) > 1
            """
        ).fetchall()
        groups = []
        for r in rows:
            ids = [int(x) for x in r["ids"].split(",")]
            key = f"isbn:{':'.join(str(i) for i in sorted(ids))}"
            if not self.is_duplicate_group_ignored(key):
                groups.append(ids)
        return groups

    def is_duplicate_group_ignored(self, group_key: str) -> bool:
        row = self._conn.execute("SELECT group_key FROM duplicate_ignores WHERE group_key = ?", (group_key,)).fetchone()
        return row is not None

    def ignore_duplicate_group(self, group_key: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO duplicate_ignores (group_key) VALUES (?)", (group_key,)
        )
        self._conn.commit()

    def merge_duplicate_books(self, keep_id: int, remove_ids: list[int], merge_user_data: bool = True) -> None:
        """Merge user data from duplicate books into keeper and delete removed entries."""
        if not remove_ids:
            return

        if merge_user_data:
            keeper = self.get_book_detail(keep_id)
            if keeper:
                best_status = keeper.status
                status_ranks = {"read": 3, "reading": 2, "want": 1, None: 0}
                notes_parts = [keeper.notes] if keeper.notes else []
                highest_rating = keeper.rating

                for rid in remove_ids:
                    dup = self.get_book_detail(rid)
                    if not dup:
                        continue
                    # Status
                    if status_ranks.get(dup.status, 0) > status_ranks.get(best_status, 0):
                        best_status = dup.status
                    # Rating
                    if highest_rating is None and dup.rating is not None:
                        highest_rating = dup.rating
                    # Notes
                    if dup.notes and dup.notes not in notes_parts:
                        notes_parts.append(dup.notes)
                    # Tags: union
                    for t in dup.tags:
                        self._conn.execute("INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)", (keep_id, t["id"]))
                    # Collections: union
                    for c in dup.collections:
                        self._conn.execute("INSERT OR IGNORE INTO collection_books (collection_id, book_id) VALUES (?, ?)", (c["id"], keep_id))
                    # Reading log: reassign
                    self._conn.execute("UPDATE reading_log SET book_id = ? WHERE book_id = ?", (keep_id, rid))

                joined_notes = "\n---\n".join(notes_parts) if notes_parts else None
                self._conn.execute(
                    "UPDATE books SET status = ?, rating = ?, notes = ? WHERE id = ?",
                    (best_status, highest_rating, joined_notes, keep_id),
                )
                self._update_tags_text([keep_id])

        # Delete remove_ids
        placeholders = ",".join("?" * len(remove_ids))
        self._conn.execute(f"DELETE FROM books WHERE id IN ({placeholders})", remove_ids)
        self._conn.commit()

    def relink_book(self, old_book_id: int, new_path: str, new_filename: str, new_folder_id: int, new_mtime: float, new_size: int) -> None:
        """Relink a moved or renamed file to its existing book entry."""
        self._conn.execute(
            """
            UPDATE books
            SET path = ?, filename = ?, folder_id = ?, file_mtime = ?, size_bytes = ?, is_missing = 0
            WHERE id = ?
            """,
            (new_path, new_filename, new_folder_id, new_mtime, new_size, old_book_id),
        )
        self._conn.commit()

    def find_missing_by_size_and_quick_hash(self, size_bytes: int, quick_hash: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM books WHERE is_missing = 1 AND size_bytes = ? AND quick_hash = ?",
            (size_bytes, quick_hash),
        ).fetchall()
        return [r["id"] for r in rows]

    # ── Custom Covers ─────────────────────────────────────────────────────────

    def set_custom_cover(self, book_id: int, rel_path: str, source: str = "custom") -> None:
        self._conn.execute(
            "UPDATE books SET cover_path = ?, cover_source = ? WHERE id = ?",
            (rel_path, source, book_id),
        )
        self._conn.commit()

    def restore_original_cover(self, book_id: int, rel_path: str | None, format: str) -> None:
        source = "placeholder" if format in ("mobi", "azw3", "djvu", "txt") else "file"
        self._conn.execute(
            "UPDATE books SET cover_path = ?, cover_source = ? WHERE id = ?",
            (rel_path, source, book_id),
        )
        self._conn.commit()

    # ── Custom Readers & Defaults ─────────────────────────────────────────────

    def list_custom_readers(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, exe_path, args_template, formats FROM custom_readers"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_custom_reader(self, name: str, exe_path: str,
                          args_template: str = "{file}", formats: str = "*") -> int:
        cur = self._conn.execute(
            "INSERT INTO custom_readers (name, exe_path, args_template, formats) VALUES (?,?,?,?)",
            (name, exe_path, args_template, formats),
        )
        self._conn.commit()
        return cur.lastrowid

    def remove_custom_reader(self, reader_id: int) -> None:
        self._conn.execute("DELETE FROM custom_readers WHERE id = ?", (reader_id,))
        self._conn.commit()

    def get_format_default(self, fmt: str) -> str | None:
        row = self._conn.execute(
            "SELECT reader_key FROM format_defaults WHERE format = ?", (fmt,)
        ).fetchone()
        return row["reader_key"] if row else None

    def set_format_default(self, fmt: str, reader_key: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO format_defaults (format, reader_key) VALUES (?,?)",
            (fmt, reader_key),
        )
        self._conn.commit()

    def rebuild_fts(self) -> None:
        try:
            self._conn.execute("INSERT INTO books_fts(books_fts) VALUES ('rebuild')")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass

    # ── V6: Recommendation Feedback ──────────────────────────────────────────

    def set_recommendation_feedback(self, book_id: int, verdict: str) -> None:
        """Record recommendation feedback: 'hide' or 'not_interested'."""
        self._conn.execute(
            "INSERT OR REPLACE INTO recommendation_feedback (book_id, verdict, created_at) "
            "VALUES (?, ?, datetime('now'))",
            (book_id, verdict),
        )
        self._conn.commit()

    def remove_recommendation_feedback(self, book_id: int) -> None:
        """Remove recommendation feedback (for undo)."""
        self._conn.execute("DELETE FROM recommendation_feedback WHERE book_id = ?", (book_id,))
        self._conn.commit()

    def get_recommendation_feedback(self) -> dict[int, str]:
        """Return dict of book_id -> verdict ('hide' | 'not_interested')."""
        rows = self._conn.execute("SELECT book_id, verdict FROM recommendation_feedback").fetchall()
        return {r["book_id"]: r["verdict"] for r in rows}

    def clear_all_recommendation_feedback(self) -> None:
        """Reset all recommendation feedback."""
        self._conn.execute("DELETE FROM recommendation_feedback")
        self._conn.commit()

    # ── V6: Web Devices & Web Download Budget ────────────────────────────────

    def add_web_device(self, name: str, token_hash: str, ip: str | None = None) -> int:
        """Register a new paired web device with token hash."""
        cur = self._conn.execute(
            "INSERT INTO web_devices (name, token_hash, last_ip, last_seen_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (name, token_hash, ip),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_web_device_by_hash(self, token_hash: str) -> dict | None:
        """Fetch active paired device by token hash."""
        row = self._conn.execute(
            "SELECT id, name, token_hash, created_at, last_seen_at, last_ip, revoked_at "
            "FROM web_devices WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        return dict(row) if row else None

    def update_web_device_seen(self, device_id: int, ip: str | None = None) -> None:
        """Update device's last seen timestamp and IP."""
        if ip:
            self._conn.execute(
                "UPDATE web_devices SET last_seen_at = datetime('now'), last_ip = ? WHERE id = ?",
                (ip, device_id),
            )
        else:
            self._conn.execute(
                "UPDATE web_devices SET last_seen_at = datetime('now') WHERE id = ?",
                (device_id,),
            )
        self._conn.commit()

    def list_web_devices(self) -> list[dict]:
        """List all paired devices ordered by last seen."""
        rows = self._conn.execute(
            "SELECT id, name, token_hash, created_at, last_seen_at, last_ip, revoked_at "
            "FROM web_devices ORDER BY last_seen_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def revoke_web_device(self, device_id: int) -> None:
        """Revoke device authorization immediately."""
        self._conn.execute(
            "UPDATE web_devices SET revoked_at = datetime('now') WHERE id = ?",
            (device_id,),
        )
        self._conn.commit()

    def delete_web_device(self, device_id: int) -> None:
        """Delete device row entirely."""
        self._conn.execute("DELETE FROM web_devices WHERE id = ?", (device_id,))
        self._conn.commit()

    def record_web_download_bytes(self, num_bytes: int) -> None:
        """Record downloaded bytes against today's local date budget."""
        today = datetime.now().strftime("%Y-%m-%d")
        key = f"web.download_bytes.{today}"
        cur_val = int(self.get_app_meta(key, "0") or "0")
        self.set_app_meta(key, str(cur_val + num_bytes))

    def get_today_web_download_bytes(self) -> int:
        """Get total web download bytes recorded for today."""
        today = datetime.now().strftime("%Y-%m-%d")
        key = f"web.download_bytes.{today}"
        return int(self.get_app_meta(key, "0") or "0")

    def can_download_web_bytes(self, num_bytes: int, daily_budget: int = 2 * 1024 * 1024 * 1024) -> bool:
        """Check if downloading num_bytes stays within the daily web download budget."""
        return (self.get_today_web_download_bytes() + num_bytes) <= daily_budget


