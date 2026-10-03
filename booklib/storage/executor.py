"""
executor.py – Executes cleanup actions safely with strict containment and lease checks.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dataclasses import dataclass
from typing import Any

from booklib.config import CACHE_MARKER_FILE, DRIVE_CACHE_DIR, COVERS_DIR
from booklib.storage.areas import get_storage_areas, has_marker
from booklib.storage.planner import CleanupPlan, CleanupAction

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    files_deleted: int
    bytes_freed: int
    errors: list[str]

    def __iter__(self):
        yield self.files_deleted
        yield self.bytes_freed
        yield self.errors

    def __getitem__(self, idx):
        return (self.files_deleted, self.bytes_freed, self.errors)[idx]


def find_marker_root(path: Path) -> Path | None:
    curr = path.parent if path.is_file() else path
    while curr != curr.parent:
        if (curr / CACHE_MARKER_FILE).exists():
            return curr
        curr = curr.parent
    return None


def is_safe_to_delete(path: Path, area_root: Path | None = None) -> bool:
    """
    Strict safety check:
    1. Area root contains .booklib-cache marker.
    2. Path is strictly inside area root.
    3. Path and parents are not symbolic links or junctions.
    """
    try:
        res_path = path.resolve()
        root = area_root
        if root is not None:
            res_root = root.resolve()
            if not res_path.is_relative_to(res_root):
                root = None

        if root is None:
            root = find_marker_root(path)

        if root is None or not (root / CACHE_MARKER_FILE).exists():
            logger.warning("Refusing to delete %s: marker file missing", path)
            return False

        res_root = root.resolve()
        if not res_path.is_relative_to(res_root) or res_path == res_root:
            logger.warning("Refusing to delete %s: outside root %s", path, root)
            return False

        # Check for symlinks/reparse points
        curr = path
        while curr != root and curr != curr.parent:
            if curr.is_symlink() or os.path.islink(str(curr)):
                logger.warning("Refusing to delete %s: symlink detected at %s", path, curr)
                return False
            curr = curr.parent

        return True
    except Exception as e:
        logger.warning("Safety check error for %s: %s", path, e)
        return False


def safe_delete_file(path: Path, area_root: Path | None = None) -> bool:
    """Safely delete a file verifying cache marker containment."""
    if not is_safe_to_delete(path, area_root):
        return False
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def execute_cleanup(conn_or_repo: Any, plan: CleanupPlan) -> CleanupResult:
    """
    Executes a CleanupPlan.
    Returns CleanupResult(files_deleted, bytes_freed, errors).
    """
    conn: sqlite3.Connection = conn_or_repo._conn if hasattr(conn_or_repo, "_conn") else conn_or_repo
    files_deleted = 0
    bytes_freed = 0
    errors: list[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    areas = get_storage_areas()

    # Ensure marker files exist
    for a in areas.values():
        a.ensure_marker()

    for act in plan.actions:
        # Special case: online cache DB cleanup
        if act.area == "online_cache":
            try:
                cur = conn.execute("DELETE FROM online_cache WHERE fetched_at < datetime('now', '-30 days')")
                conn.commit()
                if cur.rowcount > 0:
                    bytes_freed += act.size_bytes
            except Exception as e:
                errors.append(f"Online cache cleanup failed: {e}")
            continue

        if not act.path:
            continue

        area_obj = areas.get(act.area)
        area_root = area_obj.root if area_obj else DRIVE_CACHE_DIR

        # 1. Safe delete checks
        if not is_safe_to_delete(act.path, area_root):
            errors.append(f"Safety check failed for {act.path}")
            continue

        # 2. Re-check lease immediately before deletion for drive downloads
        if act.book_id:
            row = conn.execute(
                "SELECT in_use_until, last_used_at FROM drive_cache WHERE book_id = ?",
                (act.book_id,)
            ).fetchone()
            if row:
                in_use = row[0]
                if in_use and in_use > now_iso:
                    logger.info("Skipping book %d: leased until %s", act.book_id, in_use)
                    continue

        # 3. Perform file deletion
        file_existed = act.path.exists()
        try:
            if file_existed:
                act.path.unlink()
                files_deleted += 1
                bytes_freed += act.size_bytes

            # If inside drive_cache/<file_id>/, clean up the parent folder if empty
            if act.area == "drive_downloads" and act.path.parent != area_root:
                try:
                    act.path.parent.rmdir()
                except OSError:
                    pass  # directory not empty

            # 4. Remove database row
            if act.book_id:
                conn.execute("DELETE FROM drive_cache WHERE book_id = ?", (act.book_id,))
                conn.commit()

        except PermissionError as pe:
            logger.info("Cannot delete %s (locked by reader process): %s", act.path, pe)
            # Do NOT delete the database row; retry next cleanup
        except Exception as exc:
            msg = f"Failed to delete {act.path}: {exc}"
            logger.warning(msg)
            errors.append(msg)

    # Record summary in app_meta
    summary_text = f"Removed {files_deleted} files, {bytes_freed / (1024**2):.1f} MB on {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    try:
        conn.execute(
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('storage.last_cleanup', ?)",
            (summary_text,)
        )
        conn.commit()
    except Exception:
        pass

    return CleanupResult(files_deleted, bytes_freed, errors)
