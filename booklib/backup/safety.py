"""
backup/safety.py – Automatic database-only safety snapshots.

Taken before risky operations:
  - Schema migrations (handled in database.py via shutil.copy2)
  - Rename batches over 50 books
  - Bulk imports
  - Bulk online metadata runs
  - Restores

Kept in <app data>/safety/, newest 5 OR 14 days, whichever keeps more.
"""
from __future__ import annotations

import logging
import sqlite3
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from booklib.config import DATA_DIR

logger = logging.getLogger(__name__)

SAFETY_DIR = DATA_DIR / "safety"
_MAX_SNAPSHOTS = 5
_MAX_DAYS = 14
_SNAPSHOT_STEM = "snapshot-"


def take_snapshot(reason: str = "") -> Path | None:
    """
    Take a consistent database-only snapshot using SQLite's online backup API.

    Returns the path to the snapshot file, or None if the database is not open.
    """
    from booklib.config import DB_PATH
    if not DB_PATH.exists():
        return None

    SAFETY_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap_name = f"{_SNAPSHOT_STEM}{ts}.db"
    snap_path = SAFETY_DIR / snap_name

    try:
        # Use SQLite's backup API for a consistent copy even under WAL mode
        src = sqlite3.connect(str(DB_PATH))
        dst = sqlite3.connect(str(snap_path))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        logger.info("Safety snapshot taken: %s (reason: %s)", snap_path, reason or "unspecified")
    except Exception as exc:
        logger.error("Safety snapshot failed: %s", exc)
        snap_path.unlink(missing_ok=True)
        return None

    _prune_snapshots()
    return snap_path


def list_snapshots() -> list[dict]:
    """Return snapshots sorted newest-first, each as {path, taken_at, size_bytes}."""
    if not SAFETY_DIR.exists():
        return []
    snaps = []
    for p in SAFETY_DIR.glob(f"{_SNAPSHOT_STEM}*.db"):
        try:
            ts_str = p.stem[len(_SNAPSHOT_STEM):]
            taken_at = datetime.strptime(ts_str, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        snaps.append({
            "path": p,
            "taken_at": taken_at,
            "size_bytes": p.stat().st_size,
        })
    snaps.sort(key=lambda x: x["taken_at"], reverse=True)
    return snaps


def _prune_snapshots() -> None:
    """Keep newest 5 snapshots OR those within the last 14 days, whichever retains more."""
    snaps = list_snapshots()
    cutoff = datetime.now() - timedelta(days=_MAX_DAYS)

    # Determine the set to keep: by count and by age
    keep_by_count = {s["path"] for s in snaps[:_MAX_SNAPSHOTS]}
    keep_by_age   = {s["path"] for s in snaps if s["taken_at"] >= cutoff}
    keep = keep_by_count | keep_by_age

    for s in snaps:
        if s["path"] not in keep:
            try:
                s["path"].unlink()
                logger.debug("Pruned safety snapshot: %s", s["path"])
            except OSError as exc:
                logger.warning("Could not prune snapshot %s: %s", s["path"], exc)


def restore_safety_snapshot(snapshot_path: Path, target_db_path: Path | None = None) -> bool:
    """Restore a safety snapshot by copying it over the target database."""
    from booklib.config import DB_PATH
    dest = target_db_path or DB_PATH
    if not snapshot_path.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(snapshot_path), str(dest))
    return True


take_safety_snapshot = take_snapshot
list_safety_snapshots = list_snapshots
prune_safety_snapshots = _prune_snapshots
