"""
organize/undo.py – Undo a rename batch.

Processes 'done' rows in reverse order:
- If new_path exists and old_path is free → rename back, update DB.
- Otherwise → skip and report.
Then removes directories listed in created_dirs if now empty.
Marks batch undone_at.

Batches are kept for 90 days; purge_old_batches() removes older ones at startup.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_BATCH_RETENTION_DAYS = 90


def undo_batch(batch_id: str, conn: sqlite3.Connection) -> dict:
    """
    Undo a rename batch. Returns a summary dict with keys:
      restored, skipped, errors
    """
    rows = conn.execute(
        """SELECT id, book_id, old_path, new_path, created_dirs
           FROM rename_log
           WHERE batch_id = ? AND status = 'done'
           ORDER BY id DESC""",
        (batch_id,),
    ).fetchall()

    if not rows:
        return {"restored": 0, "skipped": 0, "errors": [],
                "message": "No done rows found for this batch"}

    restored = 0
    skipped = 0
    errors: list[str] = []

    for row in rows:
        old_p = Path(row["old_path"])
        new_p = Path(row["new_path"])
        if not new_p.exists():
            skipped += 1
            continue
        if old_p.exists():
            skipped += 1
            errors.append(f"Old path already occupied: {old_p}")
            continue
        try:
            old_p.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(new_p), str(old_p))
        except OSError as exc:
            errors.append(f"{new_p}: {exc}")
            skipped += 1
            continue

        # Update DB
        try:
            conn.execute(
                "UPDATE books SET path = ?, filename = ? WHERE id = ?",
                (str(old_p), old_p.name, row["book_id"]),
            )
            conn.execute(
                "UPDATE rename_log SET status = 'undone' WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            restored += 1
        except sqlite3.Error as exc:
            errors.append(f"DB update failed for book {row['book_id']}: {exc}")
            # Try to undo the filesystem rename
            try:
                os.rename(str(old_p), str(new_p))
            except OSError:
                pass
            skipped += 1

    # Remove created directories (in reverse depth order)
    all_created: list[str] = []
    for row in rows:
        if row["created_dirs"]:
            try:
                all_created.extend(json.loads(row["created_dirs"]))
            except (json.JSONDecodeError, TypeError):
                pass
    for d in sorted(set(all_created), key=lambda x: -len(x)):
        try:
            os.rmdir(d)
            logger.debug("Removed created dir on undo: %s", d)
        except OSError:
            pass  # not empty or already removed

    # Mark batch undone
    try:
        conn.execute(
            "UPDATE rename_batches SET undone_at = datetime('now') WHERE id = ?",
            (batch_id,),
        )
        conn.commit()
    except sqlite3.Error:
        pass

    return {"restored": restored, "skipped": skipped, "errors": errors}


def purge_old_batches(conn: sqlite3.Connection) -> int:
    """Remove rename batches older than 90 days (cascades to rename_log)."""
    cutoff = (datetime.now() - timedelta(days=_BATCH_RETENTION_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    try:
        cur = conn.execute(
            "DELETE FROM rename_batches WHERE created_at < ?", (cutoff,)
        )
        conn.commit()
        return cur.rowcount
    except sqlite3.Error as exc:
        logger.warning("Could not purge old rename batches: %s", exc)
        return 0
