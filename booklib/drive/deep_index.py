"""
deep_index.py – Deep indexing for Drive books: downloads, extracts real metadata and covers, and cleans up.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Callable, Any

from booklib.config import COVERS_DIR, DRIVE_CACHE_DIR
from booklib.covers import cache as cover_cache
from booklib.drive.client import DriveClient
from booklib.drive.download import ensure_local
from booklib.drive.cache import is_book_pinned, evict_book
from booklib.metadata import extract
from booklib.metadata.isbn_scan import scan_pdf_isbn

logger = logging.getLogger(__name__)


def deep_index_book(
    book_id: int,
    client: DriveClient,
    conn: sqlite3.Connection,
    keep_downloaded: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
    cancel_fn: Callable[[], bool] | None = None,
) -> bool:
    """
    Perform deep indexing on a single Drive book:
    1. Download to local cache.
    2. Extract metadata and ISBN.
    3. Generate cover thumbnail.
    4. Update database respecting field_sources.
    5. Clean up downloaded file unless pinned or keep_downloaded=True.
    """
    row = conn.execute(
        """SELECT b.id, b.filename, b.format, b.field_sources, b.cover_source, b.cover_path, b.size_bytes
           FROM books b WHERE b.id = ? AND (b.source = 'gdrive' OR b.source = 'drive')""",
        (book_id,)
    ).fetchone()

    if not row:
        return False

    bid, filename, fmt, sources_json, curr_cover_src, curr_cover_p, size_bytes = row
    sources = json.loads(sources_json or "{}")

    # 1. Ensure local copy
    try:
        local_path = ensure_local(
            book_id=bid,
            client=client,
            conn=conn,
            cancel_fn=cancel_fn,
        )
    except Exception as exc:
        logger.warning("Deep index failed to download book %d: %s", bid, exc)
        return False

    try:
        # 2. Extract metadata
        meta = extract.extract_metadata(str(local_path), fmt)

        # 3. Extract ISBN from PDF text if needed
        isbn = meta.isbn
        if fmt == "pdf" and not isbn:
            try:
                isbn = scan_pdf_isbn(str(local_path))
            except Exception:
                pass

        # 4. Save cover thumbnail if extracted
        new_cover_rel = None
        if meta.cover_bytes and curr_cover_src in ("file", "placeholder", "drive", None):
            new_cover_rel = cover_cache.save(meta.cover_bytes, bid, time.time())

        # 5. Update metadata respecting field_sources
        set_parts = ["index_level = 'deep'"]
        params: dict[str, Any] = {"id": bid}

        # Title
        if meta.title and sources.get("title") in ("file:filename", "file", None):
            set_parts.append("title = :title")
            params["title"] = meta.title
            sources["title"] = "file"

        # Author
        if meta.author and sources.get("author") in ("file:filename", "file", None):
            set_parts.append("author = :author")
            params["author"] = meta.author
            sources["author"] = "file"

        # Publisher
        if meta.publisher and sources.get("publisher") in ("file", None):
            set_parts.append("publisher = :publisher")
            params["publisher"] = meta.publisher
            sources["publisher"] = "file"

        # Year
        if meta.year and sources.get("year") in ("file", None):
            set_parts.append("year = :year")
            params["year"] = meta.year
            sources["year"] = "file"

        # Pages
        if meta.pages:
            set_parts.append("pages = :pages")
            params["pages"] = meta.pages

        # ISBN
        if isbn and sources.get("isbn") in ("file", None):
            set_parts.append("isbn = :isbn")
            params["isbn"] = isbn
            sources["isbn"] = "file"

        # Genre
        if meta.genre and sources.get("genre") in ("file", None):
            set_parts.append("genre = :genre")
            params["genre"] = meta.genre
            sources["genre"] = "file"

        # Language
        if meta.language and sources.get("language") in ("file", None):
            set_parts.append("language = :language")
            params["language"] = meta.language
            sources["language"] = "file"

        # Cover
        if new_cover_rel:
            set_parts.append("cover_path = :cover_path, cover_source = 'file'")
            params["cover_path"] = new_cover_rel

        set_parts.append("field_sources = :field_sources")
        params["field_sources"] = json.dumps(sources)

        conn.execute(f"UPDATE books SET {', '.join(set_parts)} WHERE id = :id", params)
        conn.commit()

        # 6. Delete downloaded file unless pinned or keep_downloaded
        if not keep_downloaded and not is_book_pinned(conn, bid):
            evict_book(conn, bid, force=False)

        return True

    except Exception as exc:
        logger.warning("Error deep-indexing book %d: %s", bid, exc)
        return False
