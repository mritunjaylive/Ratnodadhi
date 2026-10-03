"""
pipeline.py – per-file processing: metadata → cover → DB.
"""
from __future__ import annotations

import logging
from pathlib import Path

from booklib.covers import cache as cover_cache
from booklib.covers.placeholder import generate_placeholder
from booklib.db.repository import Repository
from booklib.duplicates.hashing import compute_quick_hash
from booklib.metadata.extract import extract_metadata

logger = logging.getLogger(__name__)


def process_file(
    path: str,
    size: int,
    mtime: float,
    folder_id: int,
    repo: Repository,
    commit: bool = True,
) -> int | None:
    """
    Process one file: extract metadata, compute quick_hash, save cover, upsert to DB.
    Returns the book id, or None on hard failure.
    """
    fmt = Path(path).suffix.lstrip(".").lower()
    filename = Path(path).name

    try:
        meta = extract_metadata(path, fmt)
    except Exception as exc:
        logger.error("Metadata extraction crashed for %s: %s", path, exc)
        meta = None
        from booklib.metadata.base import BookMeta
        meta = BookMeta()

    quick_hash = compute_quick_hash(path, size)

    # ── Upsert without cover first (to get book_id) ──────────────────────────
    try:
        book_id = repo.upsert_book(
            folder_id=folder_id,
            path=path,
            filename=filename,
            format=fmt,
            size_bytes=size,
            file_mtime=mtime,
            title=meta.title,
            author=meta.author,
            publisher=meta.publisher,
            year=meta.year,
            isbn=meta.isbn,
            pages=meta.pages,
            genre=meta.genre,
            language=meta.language,
            cover_path=None,  # will be updated below if needed
            quick_hash=quick_hash,
            series_name=getattr(meta, "series", None),
            series_index=getattr(meta, "series_index", None),
            commit=commit,
        )
    except Exception as exc:
        logger.error("DB upsert failed for %s: %s", path, exc)
        return None

    # Check if book already has custom or online cover
    curr = repo.get_book_row(book_id)
    if curr and curr.cover_source in ("custom", "online"):
        return book_id

    # ── Cover ─────────────────────────────────────────────────────────────────
    rel = cover_cache.cover_filename(book_id, mtime)
    if not cover_cache.exists(rel):
        cover_bytes = meta.cover_bytes or generate_placeholder(fmt)
        rel = cover_cache.save(cover_bytes, book_id, mtime)

    repo.update_cover(book_id, rel, cover_source="file" if meta.cover_bytes else "placeholder")
    return book_id

