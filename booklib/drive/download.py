"""
download.py – Download engine for Drive books with resume, MD5 verification, and filename sanitization.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Any

from booklib.config import DRIVE_CACHE_DIR
from booklib.drive.client import DriveClient
from booklib.drive.models import DriveFile, DriveError
from booklib.storage.guard import ensure_space

logger = logging.getLogger(__name__)

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_filename(name: str) -> str:
    """
    Sanitize filename for Windows:
    - Replace invalid chars (<>:"/\\|?*) with '_'
    - Remove control characters
    - Avoid reserved names (CON, NUL, COM1, etc.)
    - Strip trailing spaces and dots
    - Limit length to ~120 characters while preserving extension
    """
    if not name or not name.strip():
        return "unnamed_file"

    # Replace invalid chars
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name.strip())
    # Strip trailing dots and spaces
    s = s.rstrip('. ')

    # Split stem and suffix
    p = Path(s)
    stem = p.stem.rstrip('. ')
    suffix = p.suffix.lower()

    if not stem:
        stem = "file"

    # Reserved device names check
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"

    # Cap length (preserve suffix)
    max_stem_len = max(10, 120 - len(suffix))
    if len(stem) > max_stem_len:
        stem = stem[:max_stem_len].rstrip('. ')

    return f"{stem}{suffix}"


def compute_file_md5(path: Path) -> str:
    """Compute MD5 checksum of file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _invoke_progress(cb: Callable[..., None] | None, downloaded: int, total: int, speed: float) -> None:
    if not cb:
        return
    try:
        cb(downloaded, total, speed)
    except TypeError:
        try:
            cb(downloaded, total)
        except Exception:
            pass
    except Exception:
        pass


def download_drive_file(
    client: DriveClient,
    file_id: str,
    raw_filename: str | None = None,
    expected_size: int = 0,
    expected_md5: str | None = None,
    progress_callback: Callable[[int, int, float], None] | None = None,
    cancel_fn: Callable[[], bool] | None = None,
    conn: sqlite3.Connection | None = None,
    dest_dir: Path | None = None,
    filename: str | None = None,
) -> Path:
    """
    Downloads file_id from Google Drive into dest_dir or DRIVE_CACHE_DIR/<file_id>/<sanitized_filename>.
    Supports resuming partial downloads (.part).
    Verifies size and MD5 (retrying once on mismatch).
    """
    fname = filename or raw_filename or "unnamed_file"
    safe_name = sanitize_filename(fname)
    target_dir = Path(dest_dir) if dest_dir is not None else (DRIVE_CACHE_DIR / file_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    final_path = target_dir / safe_name
    part_path = target_dir / f"{safe_name}.part"

    # 1. Disk-space check with guard
    try:
        ensure_space(target_dir, needed_bytes=expected_size, purpose="book download", conn=conn)
    except Exception:
        pass

    for attempt in (1, 2):
        start_byte = 0
        if part_path.exists():
            existing_size = part_path.stat().st_size
            if existing_size < expected_size:
                start_byte = existing_size
            elif existing_size > expected_size:
                # Corrupted part file, start fresh
                part_path.unlink()
                start_byte = 0

        logger.info("Downloading file %s (start_byte=%d, total=%d, attempt=%d)", file_id, start_byte, expected_size, attempt)
        if hasattr(client, "download_file"):
            resp = client.download_file(file_id, start_byte=start_byte)
        elif hasattr(client, "download_file_stream"):
            resp = client.download_file_stream(file_id, start_byte=start_byte)
        else:
            raise DriveError("Drive client missing download method.")

        if hasattr(resp, "iter_content"):
            chunks_iter = resp.iter_content(chunk_size=1024 * 1024)
        else:
            chunks_iter = resp

        mode = "ab" if start_byte > 0 else "wb"
        downloaded = start_byte
        start_time = time.time()
        last_report = start_time

        try:
            with open(part_path, mode) as f:
                for chunk in chunks_iter:
                    if cancel_fn and cancel_fn():
                        logger.info("Download of %s cancelled by user", file_id)
                        raise DriveError("Download cancelled by user.")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_report >= 0.2:
                            elapsed = max(now - start_time, 0.001)
                            speed = (downloaded - start_byte) / elapsed
                            _invoke_progress(progress_callback, downloaded, expected_size, speed)
                            last_report = now

            _invoke_progress(progress_callback, downloaded, expected_size, 0.0)

            # Verification
            actual_size = part_path.stat().st_size
            if expected_size > 0 and actual_size != expected_size:
                if attempt == 1:
                    logger.warning("Size mismatch on download of %s (got %d, expected %d), retrying from scratch", file_id, actual_size, expected_size)
                    part_path.unlink()
                    continue
                raise DriveError(f"Download size mismatch: got {actual_size} bytes, expected {expected_size} bytes.")

            if expected_md5:
                actual_md5 = compute_file_md5(part_path)
                if actual_md5.lower() != expected_md5.lower():
                    if attempt == 1:
                        logger.warning("MD5 mismatch on download of %s (got %s, expected %s), retrying from scratch", file_id, actual_md5, expected_md5)
                        part_path.unlink()
                        continue
                    raise DriveError("Download integrity check failed (MD5 mismatch).")

            # Atomic rename to final path
            if final_path.exists():
                final_path.unlink()
            part_path.rename(final_path)
            return final_path

        except Exception as exc:
            if isinstance(exc, DriveError):
                raise
            raise DriveError(f"Failed to download file {file_id}: {exc}")

    raise DriveError(f"Download failed after retry for {file_id}")


def ensure_local(
    arg1: Any,
    arg2: Any,
    arg3: Any,
    progress_callback: Callable[..., None] | None = None,
    cancel_fn: Callable[[], bool] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    lease_minutes: int = 120,
    **kwargs: Any,
) -> Path:
    """
    Ensure a book has a valid local copy:
    - If already in cache and valid: renews lease and returns path.
    - If stale, missing, or never downloaded: downloads and records cache entry.
    Supports both (book_id, client, conn) and (repo, client, book_id) signatures.
    """
    if isinstance(arg1, int):
        book_id = arg1
        client = arg2
        conn_or_repo = arg3
    else:
        conn_or_repo = arg1
        client = arg2
        book_id = int(arg3)

    conn: sqlite3.Connection = getattr(conn_or_repo, "_conn", conn_or_repo)
    if hasattr(conn_or_repo, "conn"):
        conn = conn_or_repo.conn

    canceller = cancel_fn or cancel_check

    row = conn.execute(
        """SELECT b.drive_file_id, b.filename, b.size_bytes, b.md5,
                  c.file_path, c.md5 as cache_md5
           FROM books b
           LEFT JOIN drive_cache c ON b.id = c.book_id
           WHERE b.id = ?""",
        (book_id,)
    ).fetchone()

    if not row:
        raise ValueError(f"Book {book_id} not found in database.")

    drive_file_id, filename, size_bytes, book_md5, cache_rel, cache_md5 = row

    if not drive_file_id:
        raise ValueError(f"Book {book_id} is not a Google Drive book.")

    now_iso = datetime.now(timezone.utc).isoformat()
    lease_until = (datetime.now(timezone.utc) + timedelta(minutes=lease_minutes)).isoformat()

    # Check if existing cache is valid
    if cache_rel:
        abs_cache = DRIVE_CACHE_DIR / cache_rel
        if abs_cache.exists():
            st = abs_cache.stat()
            # If size matches and (no MD5 or MD5 matches):
            md5_matches = (not book_md5 or not cache_md5 or book_md5 == cache_md5)
            if st.st_size == size_bytes and md5_matches:
                # Renew lease
                conn.execute(
                    "UPDATE drive_cache SET last_used_at = ?, in_use_until = ? WHERE book_id = ?",
                    (now_iso, lease_until, book_id)
                )
                conn.commit()
                return abs_cache

    # Download required
    downloaded_path = download_drive_file(
        client=client,
        file_id=drive_file_id,
        raw_filename=filename,
        expected_size=size_bytes,
        expected_md5=book_md5,
        progress_callback=progress_callback,
        cancel_fn=canceller,
        conn=conn,
    )

    # Insert or update drive_cache row
    rel_path = str(downloaded_path.relative_to(DRIVE_CACHE_DIR)).replace("\\", "/")
    conn.execute(
        """INSERT OR REPLACE INTO drive_cache (book_id, file_path, size_bytes, md5, downloaded_at, last_used_at, in_use_until)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (book_id, rel_path, downloaded_path.stat().st_size, book_md5, now_iso, now_iso, lease_until)
    )
    conn.commit()

    return downloaded_path
