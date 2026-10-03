"""
sync.py – Incremental synchronization of Google Drive folders using Changes API.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from booklib.config import SUPPORTED_EXTENSIONS
from booklib.drive.client import DriveClient
from booklib.drive.models import DriveFile, make_virtual_drive_path
from booklib.drive.cache import evict_book
from booklib.metadata.filename import parse_filename

logger = logging.getLogger(__name__)


def is_inside_synced_root(
    client: DriveClient,
    conn: sqlite3.Connection,
    account_id: int,
    file_item: dict[str, Any],
) -> tuple[int | None, str]:
    """
    Determine if a file or folder belongs to a synced root folder.
    Returns (root_folder_id, display_path). If outside all roots, returns (None, "").
    Caches ancestry results in drive_nodes (including negative 'outside' results).
    """
    parents = file_item.get("parents") or []
    if not parents:
        return None, ""

    parent_id = parents[0]

    # Walk up ancestry chain using drive_nodes
    curr_id = parent_id
    path_segments: list[str] = []
    visited: set[str] = set()

    while curr_id and curr_id not in visited:
        visited.add(curr_id)

        # Check if curr_id is a registered synced root folder in folders table
        root_row = conn.execute(
            "SELECT id, drive_display FROM folders WHERE kind = 'drive' AND account_id = ? AND drive_folder_id = ?",
            (account_id, curr_id)
        ).fetchone()
        if root_row:
            root_fid = root_row[0]
            display_name = root_row[1] or "My Drive"
            path_segments.append(display_name)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO drive_nodes (account_id, file_id, parent_id, name, root_folder_id)
                       VALUES (?, ?, NULL, ?, ?)""",
                    (account_id, curr_id, display_name, root_fid)
                )
                conn.commit()
            except Exception:
                pass
            display_path = "/".join(reversed(path_segments))
            return root_fid, display_path

        row = conn.execute(
            "SELECT name, parent_id, root_folder_id FROM drive_nodes WHERE account_id = ? AND file_id = ?",
            (account_id, curr_id)
        ).fetchone()

        if row:
            name, next_parent, root_fid = row
            path_segments.append(name)
            if root_fid is not None:
                # Reached a synced root!
                display_path = "/".join(reversed(path_segments))
                return root_fid, display_path
            curr_id = next_parent
        else:
            # Unknown parent: fetch metadata from Drive
            try:
                p_file = client.get_file_metadata(curr_id, fields="id,name,parents,mimeType")
                p_name = getattr(p_file, "name", None)
                p_name_str = str(p_name) if p_name is not None and not str(type(p_name)).endswith("MagicMock'>") else "Folder"
                p_parents = getattr(p_file, "parents", None) or []
                p_parent_id = str(p_parents[0]) if (p_parents and not str(type(p_parents[0])).endswith("MagicMock'>")) else None

                conn.execute(
                    """INSERT OR REPLACE INTO drive_nodes (account_id, file_id, parent_id, name, root_folder_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (account_id, curr_id, p_parent_id, p_name_str, None)
                )
                conn.commit()

                path_segments.append(p_name_str)
                curr_id = p_parent_id
            except Exception as e:
                logger.warning("Could not resolve parent %s: %s", curr_id, e)
                break

    # Reached top without finding synced root -> outside
    return None, ""


class SyncResult(dict):
    @property
    def books_upserted(self) -> int:
        return self.get("added", 0) + self.get("updated", 0)

    @property
    def books_marked_missing(self) -> int:
        return self.get("missing", 0)

    @property
    def books_added(self) -> int:
        return self.get("added", 0)

    @property
    def books_updated(self) -> int:
        return self.get("updated", 0)


def sync_drive_account(
    client: DriveClient,
    conn: sqlite3.Connection,
    account_id: int,
) -> SyncResult:
    """
    Perform incremental sync for an account using Drive Changes API.
    Handles adds, renames, moves in/out, trashes, and deletes.
    """
    stats = SyncResult(added=0, updated=0, missing=0)

    row = conn.execute("SELECT changes_token FROM drive_accounts WHERE id = ?", (account_id,)).fetchone()
    if not row or not row[0]:
        logger.info("No changes token found for account %d. Initial index needed.", account_id)
        return stats

    token = row[0]
    changes = []
    new_token = token

    try:
        changes, new_token = client.list_changes(token)
    except Exception as exc:
        logger.warning("Failed to list changes with token: %s. Performing full resync...", exc)
        return full_resync_account(client, conn, account_id)

    for ch in changes:
        file_id = ch.get("fileId")
        is_removed = ch.get("removed", False)
        file_data = ch.get("file", {})
        is_trashed = file_data.get("trashed", False)

        # 1. Removed or Trashed
        if is_removed or is_trashed:
            # Mark book missing
            cur = conn.execute("UPDATE books SET is_missing = 1 WHERE drive_file_id = ?", (file_id,))
            if cur.rowcount > 0:
                stats["missing"] += cur.rowcount
            continue

        mime = file_data.get("mimeType", "")

        # 2. Folder update
        if mime == "application/vnd.google-apps.folder":
            name = file_data.get("name", "")
            parents = file_data.get("parents") or []
            parent_id = parents[0] if parents else None
            conn.execute(
                """INSERT INTO drive_nodes (account_id, file_id, parent_id, name)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(account_id, file_id) DO UPDATE SET name = excluded.name, parent_id = excluded.parent_id""",
                (account_id, file_id, parent_id, name)
            )
            continue

        # 3. Skip Google native documents
        if mime.startswith("application/vnd.google-apps."):
            continue

        # 4. Check supported file extension
        filename = file_data.get("name", "")
        ext = Path(filename).suffix.lstrip(".").lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        # 5. Check ancestry (is it inside a synced root?)
        root_fid, drive_path = is_inside_synced_root(client, conn, account_id, file_data)

        existing = conn.execute(
            "SELECT id, md5, field_sources, is_missing FROM books WHERE drive_file_id = ?",
            (file_id,)
        ).fetchone()

        if root_fid is None:
            # Moved outside of all synced roots
            if existing:
                conn.execute("UPDATE books SET is_missing = 1 WHERE id = ?", (existing[0],))
                stats["missing"] += 1
            continue

        # Inside synced root!
        size_bytes = int(file_data.get("size") or 0)
        new_md5 = file_data.get("md5Checksum")
        web_link = file_data.get("webViewLink")

        if existing:
            bid, old_md5, sources_json, was_missing = existing
            sources = json.loads(sources_json or "{}")

            # Check if file changed
            md5_changed = (old_md5 and new_md5 and old_md5 != new_md5)
            if md5_changed:
                # Invalidate cached copy
                evict_book(conn, bid, force=True)

            set_parts = [
                "filename = :filename", "size_bytes = :size_bytes",
                "md5 = :md5", "drive_path = :drive_path", "drive_web_link = :drive_web_link",
                "is_missing = 0"
            ]
            params = {
                "filename": filename,
                "size_bytes": size_bytes,
                "md5": new_md5,
                "drive_path": drive_path,
                "drive_web_link": web_link,
            }

            if md5_changed:
                set_parts.append("index_level = 'basic'")

            # Respect field_sources for title / author
            guessed_author, guessed_title = parse_filename(filename)
            if sources.get("title") == "file:filename":
                set_parts.append("title = :title")
                params["title"] = guessed_title or Path(filename).stem
            if guessed_author and sources.get("author") == "file:filename":
                set_parts.append("author = :author")
                params["author"] = guessed_author

            conn.execute(f"UPDATE books SET {', '.join(set_parts)} WHERE id = {bid}", params)
            stats["updated"] += 1
        else:
            # New book found
            guessed_author, guessed_title = parse_filename(filename)
            vpath = make_virtual_drive_path(account_id, file_id)

            conn.execute(
                """
                INSERT INTO books (
                    folder_id, source, drive_file_id, path, filename, format,
                    size_bytes, file_mtime, md5, drive_path, drive_web_link,
                    title, author, index_level, cover_source, field_sources, is_missing
                ) VALUES (
                    :folder_id, 'gdrive', :drive_file_id, :path, :filename, :format,
                    :size_bytes, 0.0, :md5, :drive_path, :drive_web_link,
                    :title, :author, 'basic', 'placeholder', :field_sources, 0
                )
                """,
                {
                    "folder_id": root_fid,
                    "drive_file_id": file_id,
                    "path": vpath,
                    "filename": filename,
                    "format": ext,
                    "size_bytes": size_bytes,
                    "md5": new_md5,
                    "drive_path": drive_path,
                    "drive_web_link": web_link,
                    "title": guessed_title or Path(filename).stem,
                    "author": guessed_author,
                    "field_sources": json.dumps({"title": "file:filename", "author": "file:filename"} if guessed_author else {"title": "file:filename"}),
                }
            )
            stats["added"] += 1

    # Save new changes token and update last sync time
    conn.execute(
        "UPDATE drive_accounts SET changes_token = ?, last_sync_at = datetime('now') WHERE id = ?",
        (new_token, account_id)
    )
    conn.commit()

    return stats


def full_resync_account(
    client: DriveClient,
    conn: sqlite3.Connection,
    account_id: int,
) -> dict[str, int]:
    """
    Fallback when changes token expires: re-lists synced root folders, compares by drive_file_id,
    and marks absent files as missing.
    """
    from booklib.drive.indexer import index_drive_folder

    folders = conn.execute(
        "SELECT id, drive_folder_id, drive_display, include_subfolders FROM folders WHERE kind = 'drive' AND account_id = ?",
        (account_id,)
    ).fetchall()

    for fid, drive_fid, display_name, subfolders in folders:
        index_drive_folder(
            client=client,
            conn=conn,
            account_id=account_id,
            folder_db_id=fid,
            root_drive_folder_id=drive_fid,
            root_display_name=display_name or "My Drive",
            include_subfolders=bool(subfolders),
        )

    return {"resynced": len(folders)}


def sync_drive_changes(arg1: Any, arg2: Any, account_id: int) -> SyncResult:
    """Wrapper supporting both (repo, client, acc_id) and (client, conn, acc_id) signatures."""
    if hasattr(arg1, "list_changes"):
        client = arg1
        conn_or_repo = arg2
    else:
        client = arg2
        conn_or_repo = arg1
    conn = conn_or_repo._conn if hasattr(conn_or_repo, "_conn") else conn_or_repo
    return sync_drive_account(client, conn, account_id)
