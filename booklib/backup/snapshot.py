"""
backup/snapshot.py – Consistent database snapshot creation and integrity verification.
"""
from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class SnapshotError(Exception):
    """Raised when database snapshot creation or integrity check fails."""


def take_db_snapshot(
    conn: sqlite3.Connection,
    target_path: Path | None = None,
) -> Path:
    """
    Take a consistent snapshot of the active SQLite database using the online backup API.
    Runs PRAGMA integrity_check on the snapshot.
    Returns the path to the verified snapshot file.
    """
    if target_path is None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            target_path = Path(tmp.name)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)

    dest_conn: sqlite3.Connection | None = None
    try:
        dest_conn = sqlite3.connect(str(target_path))
        conn.backup(dest_conn)

        # Integrity verification
        cursor = dest_conn.execute("PRAGMA integrity_check")
        rows = cursor.fetchall()
        if not rows or rows[0][0] != "ok":
            detail = "; ".join(r[0] for r in rows) if rows else "empty response"
            raise SnapshotError(f"Database integrity check failed on snapshot: {detail}")

        return target_path
    except Exception as exc:
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
        raise SnapshotError(f"Failed to create database snapshot: {exc}") from exc
    finally:
        if dest_conn is not None:
            dest_conn.close()
