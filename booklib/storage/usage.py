"""
usage.py – Utility functions to measure cache and storage usage.
"""
from __future__ import annotations

import os
from pathlib import Path
from booklib.config import DRIVE_CACHE_DIR, COVERS_DIR


def measure_directory_bytes(path: Path) -> int:
    """Recursively calculate size in bytes of all regular files in directory."""
    if not path.exists():
        return 0
    total = 0
    try:
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    fp = os.path.join(root, f)
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except Exception:
        pass
    return total


def get_cache_usage_summary(conn) -> dict:
    """Return dictionary with cache size, count of downloaded books, and limit."""
    drive_cache_size = measure_directory_bytes(DRIVE_CACHE_DIR)
    row = conn.execute("SELECT COUNT(*) FROM drive_cache").fetchone()
    count = row[0] if row else 0

    meta_row = conn.execute("SELECT value FROM app_meta WHERE key = 'storage.cache_limit_bytes'").fetchone()
    limit = int(meta_row[0]) if meta_row else (5 * 1024 * 1024 * 1024)

    return {
        "used_bytes": drive_cache_size,
        "book_count": count,
        "limit_bytes": limit,
    }


def get_cache_usage_bytes(path: Path | None = None) -> int:
    """Return total bytes used in drive cache."""
    return measure_directory_bytes(path or DRIVE_CACHE_DIR)


def count_cached_books(repo_or_conn) -> int:
    """Return number of cached books in drive_cache."""
    conn = repo_or_conn._conn if hasattr(repo_or_conn, "_conn") else repo_or_conn
    row = conn.execute("SELECT COUNT(*) FROM drive_cache").fetchone()
    return row[0] if row else 0
