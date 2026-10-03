"""
scheduler.py – Startup consistency repairs and automatic cleanup scheduling.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from booklib.config import DRIVE_CACHE_DIR, CACHE_MARKER_FILE
from booklib.storage.areas import get_storage_areas
from booklib.storage.planner import plan_cleanup
from booklib.storage.executor import execute_cleanup

logger = logging.getLogger(__name__)


def run_startup_consistency_check(conn_or_repo: Any) -> None:
    """
    Consistency check run at application startup:
    1. Remove drive_cache rows whose files are missing from disk.
    2. Delete orphan files in cache folder older than 1 day that have no database row.
    3. Delete stale .part files older than 7 days.
    4. Delete leftover temp indexing files.
    """
    conn: sqlite3.Connection = conn_or_repo._conn if hasattr(conn_or_repo, "_conn") else conn_or_repo
    logger.info("Running storage startup consistency repair...")
    areas = get_storage_areas()
    for a in areas.values():
        a.ensure_marker()

    now_ts = time.time()

    # 1. Clean missing rows
    try:
        rows = conn.execute("SELECT book_id, file_path FROM drive_cache").fetchall()
        for bid, rel_path in rows:
            abs_p = Path(rel_path) if Path(rel_path).is_absolute() else (DRIVE_CACHE_DIR / rel_path)
            if not abs_p.exists():
                logger.info("Startup repair: removing drive_cache row for missing file %s", rel_path)
                conn.execute("DELETE FROM drive_cache WHERE book_id = ?", (bid,))
        conn.commit()
    except Exception as e:
        logger.warning("Startup repair error cleaning rows: %s", e)

    # 2. Delete orphan files in DRIVE_CACHE_DIR
    if DRIVE_CACHE_DIR.exists():
        try:
            valid_rows = conn.execute("SELECT file_path FROM drive_cache").fetchall()
            valid_paths = {Path(r[0]).resolve() for r in valid_rows}

            for root_dir, _, files in os.walk(DRIVE_CACHE_DIR):
                for f in files:
                    if f == CACHE_MARKER_FILE:
                        continue
                    fp = Path(root_dir) / f
                    if f.endswith(".part"):
                        # Check age: older than 7 days
                        if now_ts - fp.stat().st_mtime > 7 * 86400:
                            try:
                                fp.unlink()
                            except OSError:
                                pass
                    elif fp.resolve() not in valid_paths:
                        # Orphan file: older than 1 day
                        if now_ts - fp.stat().st_mtime > 86400:
                            try:
                                fp.unlink()
                                # Clean up parent if empty
                                try:
                                    fp.parent.rmdir()
                                except OSError:
                                    pass
                            except OSError:
                                pass
        except Exception as e:
            logger.warning("Startup repair error cleaning orphan files: %s", e)


def run_routine_cleanup(conn: sqlite3.Connection, exclude_book_ids: set[int] | None = None) -> tuple[int, int, list[str]]:
    """Runs standard routine cleanup according to policy."""
    plan = plan_cleanup(conn, reason="scheduled", exclude_book_ids=exclude_book_ids)
    if plan.actions:
        return execute_cleanup(conn, plan)
    return (0, 0, [])
