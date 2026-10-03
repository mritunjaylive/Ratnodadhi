"""
storage/tempfiles.py – Registry of temporary files created outside the app's own folders.

Usage:
    register_temp(path, purpose)   # BEFORE creating the file
    release_temp(path)             # AFTER renaming to final name or on failure/cancel

Startup sweep: every registered path whose filename matches the temp pattern
for its purpose is deleted (safe_delete checks apply) and its row removed.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Temp naming patterns per purpose (used to validate before deleting)
_TEMP_PATTERNS: dict[str, re.Pattern] = {
    "convert": re.compile(r"^.+\.tmp-[0-9a-f\-]{36}\.[a-z0-9]+$", re.IGNORECASE),
    "rename":  re.compile(r"^\.[0-9a-f\-]{36}\.tmp$", re.IGNORECASE),
    "copy":    re.compile(r"^.+\.tmp-[0-9a-f\-]{36}$", re.IGNORECASE),
    "export":  re.compile(r"^.+\.tmp-[0-9a-f\-]{36}\.(csv|json)$", re.IGNORECASE),
    "backup":  re.compile(r"^.+\.tmp-[0-9a-f\-]{36}\.zip$", re.IGNORECASE),
}


class TempFileRegistry:
    """Wraps a SQLite connection to manage the temp_files table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def register(self, path: Path | str, purpose: str) -> None:
        """Record a temp file BEFORE creating it."""
        path = str(path)
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO temp_files (path, purpose) VALUES (?, ?)",
                (path, purpose),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Could not register temp file %s: %s", path, exc)

    def release(self, path: Path | str) -> None:
        """Remove the record after the file has been finalized or deleted."""
        path = str(path)
        try:
            self._conn.execute("DELETE FROM temp_files WHERE path = ?", (path,))
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Could not release temp file %s: %s", path, exc)

    def sweep(self) -> int:
        """
        Called at startup: delete every registered temp file that still exists
        and whose filename matches its purpose pattern. Returns number removed.
        """
        try:
            rows = self._conn.execute(
                "SELECT path, purpose FROM temp_files"
            ).fetchall()
        except sqlite3.Error:
            return 0

        removed = 0
        for row in rows:
            path_str, purpose = row["path"], row["purpose"]
            p = Path(path_str)
            pattern = _TEMP_PATTERNS.get(purpose)
            if pattern and pattern.match(p.name) and p.exists():
                try:
                    p.unlink()
                    logger.info("Swept leftover temp file: %s (%s)", p, purpose)
                    removed += 1
                except OSError as exc:
                    logger.warning("Could not sweep temp file %s: %s", p, exc)
            # Remove the registry row regardless of whether the file existed
            try:
                self._conn.execute("DELETE FROM temp_files WHERE path = ?", (path_str,))
            except sqlite3.Error:
                pass

        if rows:
            try:
                self._conn.commit()
            except sqlite3.Error:
                pass

        return removed

    def all_entries(self) -> list[dict]:
        """Return all registered temp entries."""
        try:
            rows = self._conn.execute(
                "SELECT path, purpose, created_at FROM temp_files ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []
