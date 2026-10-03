"""
organize/executor.py – Journaled rename execution and crash recovery.

Runs as a maintenance-lane job. Steps:
1. (Optionally) take a safety snapshot for batches > 50 books.
2. Write rename_batches row + all rename_log rows (status='pending') BEFORE touching files.
3. For each row: re-verify, create dirs, rename, update DB, mark done.
4. Register own-changes paths in the watcher's own-changes set.
5. Optionally remove empty dirs left behind.
6. On startup: recover any 'pending' rows from crashed sessions.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Callable

from booklib.organize.planner import RenameRow

logger = logging.getLogger(__name__)

# Snapshot threshold
_SNAPSHOT_THRESHOLD = 50


def _paths_equal(a: str, b: str) -> bool:
    return a.lower() == b.lower() if sys.platform == "win32" else a == b


class RenameExecutor:
    """
    Executes a rename batch from a list of RenameRow objects.

    *conn*: writable SQLite connection
    *on_progress*: optional callback(done, total, message)
    *own_changes*: optional set to register renamed paths (watcher ignores them)
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        on_progress: Callable[[int, int, str], None] | None = None,
        own_changes: set[str] | None = None,
        remove_empty_dirs: bool = False,
    ) -> None:
        self._conn = conn
        self._on_progress = on_progress or (lambda d, t, m: None)
        self._own_changes = own_changes if own_changes is not None else set()
        self._remove_empty_dirs = remove_empty_dirs

    def execute(
        self,
        rows: list[RenameRow],
        file_pattern: str,
        folder_pattern: str = "",
    ) -> dict:
        """Execute only rows with status='OK'. Returns a summary dict."""
        ok_rows = [r for r in rows if r.status == "OK"]
        if not ok_rows:
            return {"renamed": 0, "failed": 0, "errors": []}

        # Safety snapshot for large batches
        if len(ok_rows) > _SNAPSHOT_THRESHOLD:
            try:
                from booklib.backup.safety import take_snapshot
                from booklib.config import DB_PATH
                from booklib.storage.guard import guard_safety_snapshot
                guard_safety_snapshot(DB_PATH, self._conn)
                take_snapshot(f"before rename batch of {len(ok_rows)} books")
            except Exception as exc:
                logger.warning("Safety snapshot failed (continuing): %s", exc)

        # Write-ahead journal
        batch_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO rename_batches (id, file_pattern, folder_pattern) VALUES (?, ?, ?)",
            (batch_id, file_pattern, folder_pattern or ""),
        )
        for row in ok_rows:
            self._conn.execute(
                """INSERT INTO rename_log
                   (batch_id, book_id, old_path, new_path, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (batch_id, row.book_id, row.old_path, row.new_path),
            )
        self._conn.commit()

        # Execute renames
        renamed, failed = 0, 0
        errors: list[dict] = []
        created_dirs_per_row: dict[int, list[str]] = {}

        for i, row in enumerate(ok_rows):
            self._on_progress(i, len(ok_rows), f"Renaming {Path(row.old_path).name}…")
            result = self._rename_one(row, batch_id)
            if result["ok"]:
                renamed += 1
                created_dirs_per_row[row.book_id] = result.get("created_dirs", [])
            else:
                failed += 1
                errors.append({"path": row.old_path, "reason": result["reason"]})

        self._on_progress(len(ok_rows), len(ok_rows), "Done")

        # Remove empty dirs if requested
        if self._remove_empty_dirs:
            self._cleanup_empty_dirs(ok_rows)

        return {"batch_id": batch_id, "renamed": renamed, "failed": failed, "errors": errors}

    def _rename_one(self, row: RenameRow, batch_id: str) -> dict:
        src = Path(row.old_path)
        dst = Path(row.new_path)

        # Re-verify source
        if not src.exists():
            self._mark_log(row, batch_id, "failed", "Source disappeared after preview")
            return {"ok": False, "reason": "Source disappeared after preview"}
        try:
            stat = src.stat()
            if row.size and stat.st_size != row.size:
                self._mark_log(row, batch_id, "failed", "File changed since preview")
                return {"ok": False, "reason": "File changed since preview"}
        except OSError:
            pass

        # Create directories
        created_dirs: list[str] = []
        if dst.parent != src.parent:
            for parent in reversed(list(dst.parents)):
                if not parent.exists():
                    try:
                        parent.mkdir(parents=True, exist_ok=True)
                        created_dirs.append(str(parent))
                    except OSError as exc:
                        self._mark_log(row, batch_id, "failed", f"mkdir failed: {exc}")
                        return {"ok": False, "reason": f"Could not create directory: {exc}"}
                    break

        # Update created_dirs in log
        if created_dirs:
            self._conn.execute(
                "UPDATE rename_log SET created_dirs = ? WHERE batch_id = ? AND book_id = ?",
                (json.dumps(created_dirs), batch_id, row.book_id),
            )

        # Register own-changes paths
        self._own_changes.add(str(src))
        self._own_changes.add(str(dst))

        # Perform rename
        case_only = _paths_equal(str(src), str(dst)) and str(src) != str(dst)
        try:
            if case_only:
                # Two-step rename for case-only changes on Windows
                tmp_name = src.parent / f".{uuid.uuid4()}.tmp"
                from booklib.storage.tempfiles import TempFileRegistry
                reg = TempFileRegistry(self._conn)
                reg.register(tmp_name, "rename")
                os.rename(src, tmp_name)
                os.rename(tmp_name, dst)
                reg.release(tmp_name)
            else:
                os.rename(src, dst)
        except PermissionError as exc:
            self._mark_log(row, batch_id, "failed", "File in use (permission denied)")
            return {"ok": False, "reason": "File is open in a reader (permission denied)"}
        except OSError as exc:
            if dst.exists():
                self._mark_log(row, batch_id, "failed", "Target exists (race condition)")
                return {"ok": False, "reason": "Target file appeared after preview"}
            self._mark_log(row, batch_id, "failed", str(exc))
            return {"ok": False, "reason": str(exc)}

        # Update DB
        try:
            self._conn.execute(
                "UPDATE books SET path = ?, filename = ? WHERE id = ?",
                (str(dst), dst.name, row.book_id),
            )
            self._mark_log(row, batch_id, "done")
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.error("DB update failed after rename, rolling back: %s", exc)
            try:
                os.rename(dst, src)
            except OSError:
                pass
            self._mark_log(row, batch_id, "failed", f"Database update failed: {exc}")
            return {"ok": False, "reason": f"Database update failed: {exc}"}

        return {"ok": True, "created_dirs": created_dirs}

    def _mark_log(self, row: RenameRow, batch_id: str, status: str, error: str = "") -> None:
        try:
            self._conn.execute(
                "UPDATE rename_log SET status = ?, error = ? WHERE batch_id = ? AND book_id = ?",
                (status, error or None, batch_id, row.book_id),
            )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def _cleanup_empty_dirs(self, rows: list[RenameRow]) -> None:
        """Remove empty directories that were created by this batch."""
        dirs_to_check: set[str] = set()
        for row in rows:
            dirs_to_check.add(str(Path(row.old_path).parent))
        for d in sorted(dirs_to_check, reverse=True):
            try:
                os.rmdir(d)
                logger.debug("Removed empty dir: %s", d)
            except OSError:
                pass  # Not empty or not removable — ignore


def recover_pending_renames(conn: sqlite3.Connection) -> int:
    """
    Called at startup: resolve any 'pending' rename_log rows from crashed sessions.
    Returns the count of rows recovered/resolved.
    """
    try:
        rows = conn.execute(
            """SELECT rl.id, rl.book_id, rl.old_path, rl.new_path, rl.batch_id
               FROM rename_log rl
               WHERE rl.status = 'pending'"""
        ).fetchall()
    except sqlite3.OperationalError:
        return 0  # table doesn't exist yet

    recovered = 0
    for row in rows:
        old_p = Path(row["old_path"])
        new_p = Path(row["new_path"])
        if new_p.exists() and not old_p.exists():
            # Rename succeeded but DB update didn't — finish it
            try:
                conn.execute(
                    "UPDATE books SET path = ?, filename = ? WHERE id = ?",
                    (str(new_p), new_p.name, row["book_id"]),
                )
                conn.execute(
                    "UPDATE rename_log SET status = 'done' WHERE id = ?",
                    (row["id"],),
                )
                conn.commit()
                recovered += 1
                logger.info("Crash recovery: marked rename done for book %s", row["book_id"])
            except sqlite3.Error as exc:
                logger.warning("Crash recovery failed for row %d: %s", row["id"], exc)
        elif old_p.exists():
            # Rename didn't happen — mark failed
            try:
                conn.execute(
                    "UPDATE rename_log SET status = 'failed', error = 'Recovered at startup (rename did not happen)' WHERE id = ?",
                    (row["id"],),
                )
                conn.commit()
                recovered += 1
            except sqlite3.Error:
                pass

    return recovered
