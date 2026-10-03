"""
indexer.py – Initial indexing of a Google Drive folder tree into the library.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from booklib.config import SUPPORTED_EXTENSIONS, SCAN_BATCH_SIZE
from booklib.drive.client import DriveClient
from booklib.drive.models import DriveFile, make_virtual_drive_path
from booklib.metadata.filename import parse_filename

logger = logging.getLogger(__name__)


@dataclass
class IndexSummary:
    added_books: int = 0
    updated_books: int = 0
    skipped_google_docs: int = 0
    skipped_unsupported: int = 0
    folders_indexed: int = 0
    errors: list[str] = None  # type: ignore

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def books_indexed(self) -> int:
        return self.added_books + self.updated_books

    @property
    def google_docs_skipped(self) -> int:
        return self.skipped_google_docs


def index_drive_folder(
    arg1: Any,
    arg2: Any,
    account_id: int,
    folder_db_id: int,
    root_drive_folder_id: str,
    root_display_name: str = "My Drive",
    include_subfolders: bool = True,
    progress_callback: Callable[[int, int, str], None] | None = None,
    cancel_fn: Callable[[], bool] | None = None,
    folder_path: str | None = None,
    create_collections: bool = False,
    **kwargs: Any,
) -> IndexSummary:
    """
    Perform breadth-first indexing of a Drive folder:
    1. Record changes start token.
    2. Traverse folders and upsert into drive_nodes.
    3. Parse filenames and batch upsert into books.
    4. Save start token in drive_accounts.
    Supports both (client, conn, ...) and (repo, client, ...) calling patterns.
    """
    if hasattr(arg1, "list_files") or hasattr(arg1, "list_folder_contents"):
        client: DriveClient = arg1
        conn_or_repo = arg2
    else:
        conn_or_repo = arg1
        client = arg2

    conn: sqlite3.Connection = getattr(conn_or_repo, "_conn", conn_or_repo)
    if hasattr(conn_or_repo, "conn"):
        conn = conn_or_repo.conn

    root_display = folder_path or root_display_name or "My Drive"
    summary = IndexSummary()

    # 1. Capture changes start token at beginning of walk
    start_token = None
    try:
        start_token = client.get_changes_start_token()
    except Exception as e:
        logger.warning("Could not fetch start page token: %s", e)

    # Queue of (drive_folder_id, current_display_path)
    queue: deque[tuple[str, str]] = deque([(root_drive_folder_id, root_display)])
    visited_folders: set[str] = set()

    # Seed root node into drive_nodes
    conn.execute(
        """INSERT OR REPLACE INTO drive_nodes (account_id, file_id, parent_id, name, root_folder_id)
           VALUES (?, ?, NULL, ?, ?)""",
        (account_id, root_drive_folder_id, root_display, folder_db_id)
    )
    conn.commit()

    book_batch: list[dict[str, Any]] = []

    def flush_book_batch():
        if not book_batch:
            return
        for b in book_batch:
            # Check existing book by drive_file_id
            existing = conn.execute(
                "SELECT id, field_sources FROM books WHERE drive_file_id = ?",
                (b["drive_file_id"],)
            ).fetchone()

            if existing:
                # Update without overwriting manual / online edits
                bid = existing[0]
                sources = json.loads(existing[1] or "{}")
                set_parts = [
                    "filename = :filename", "size_bytes = :size_bytes", "file_mtime = :file_mtime",
                    "md5 = :md5", "drive_path = :drive_path", "drive_web_link = :drive_web_link",
                    "is_missing = 0"
                ]
                params = dict(b)

                # Only update title if not manually edited
                if sources.get("title") != "manual":
                    set_parts.append("title = :title")
                if sources.get("author") != "manual":
                    set_parts.append("author = :author")

                conn.execute(f"UPDATE books SET {', '.join(set_parts)} WHERE id = {bid}", params)
                summary.updated_books += 1
            else:
                conn.execute(
                    """
                    INSERT INTO books (
                        folder_id, source, drive_file_id, path, filename, format,
                        size_bytes, file_mtime, md5, drive_path, drive_web_link,
                        title, author, index_level, cover_source, field_sources, is_missing
                    ) VALUES (
                        :folder_id, :source, :drive_file_id, :path, :filename, :format,
                        :size_bytes, :file_mtime, :md5, :drive_path, :drive_web_link,
                        :title, :author, :index_level, :cover_source, :field_sources, 0
                    )
                    """,
                    b
                )
                summary.added_books += 1

        conn.commit()
        book_batch.clear()

    # Breadth-first traversal
    while queue:
        if cancel_fn and cancel_fn():
            logger.info("Drive indexing cancelled by user.")
            break

        # Process a batch of folders together (up to 20 folders)
        curr_folders = []
        while queue and len(curr_folders) < 20:
            f_id, f_path = queue.popleft()
            if f_id not in visited_folders:
                visited_folders.add(f_id)
                curr_folders.append((f_id, f_path))

        if not curr_folders:
            continue

        parent_ids = [fid for fid, _ in curr_folders]
        folder_paths = {fid: fpath for fid, fpath in curr_folders}

        try:
            items = client.list_folder_contents(parent_ids)
        except Exception as exc:
            msg = f"Failed to list folder batch: {exc}"
            logger.warning(msg)
            summary.errors.append(msg)
            continue

        summary.folders_indexed += len(curr_folders)

        for item in items:
            parent_display = folder_paths.get(item.parents[0] if item.parents else "", root_display_name)

            # 1. Folder
            if item.is_folder:
                sub_path = f"{parent_display}/{item.name}"
                conn.execute(
                    """INSERT OR REPLACE INTO drive_nodes (account_id, file_id, parent_id, name, root_folder_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (account_id, item.id, item.parents[0] if item.parents else None, item.name, folder_db_id)
                )
                if include_subfolders and item.id not in visited_folders:
                    queue.append((item.id, sub_path))
                continue

            # 2. Shortcut
            if item.is_shortcut and item.shortcut_target_id:
                try:
                    target_file = client.get_file_metadata(item.shortcut_target_id)
                    item = target_file
                except Exception:
                    continue

            # 3. Google native apps (Docs, Sheets, Slides)
            if item.mime_type.startswith("application/vnd.google-apps."):
                summary.skipped_google_docs += 1
                continue

            # 4. Check supported extension
            ext = Path(item.name).suffix.lstrip(".").lower()
            if ext not in SUPPORTED_EXTENSIONS:
                summary.skipped_unsupported += 1
                continue

            # 5. Book file
            guessed_author, guessed_title = parse_filename(item.name)
            vpath = make_virtual_drive_path(account_id, item.id)

            book_batch.append({
                "folder_id": folder_db_id,
                "source": "gdrive",
                "drive_file_id": item.id,
                "path": vpath,
                "filename": item.name,
                "format": ext,
                "size_bytes": item.size,
                "file_mtime": 0.0,
                "md5": item.md5,
                "drive_path": parent_display,
                "drive_web_link": item.web_view_link,
                "title": guessed_title or Path(item.name).stem,
                "author": guessed_author,
                "index_level": "basic",
                "cover_source": "placeholder",
                "field_sources": json.dumps({"title": "file:filename", "author": "file:filename"} if guessed_author else {"title": "file:filename"}),
            })

            if len(book_batch) >= 100:
                flush_book_batch()
                if progress_callback:
                    progress_callback(summary.added_books + summary.updated_books, 0, f"Indexed {summary.added_books} books...")

    flush_book_batch()

    # Save changes start token
    if start_token:
        conn.execute("UPDATE drive_accounts SET changes_token = ? WHERE id = ?", (start_token, account_id))
        conn.commit()

    return summary
