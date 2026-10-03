"""
guard.py – Disk-space precheck with emergency cleanup tier execution.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

from booklib.storage.policy import load_storage_policy
from booklib.storage.planner import plan_cleanup
from booklib.storage.executor import execute_cleanup

logger = logging.getLogger(__name__)


class LowDiskSpace(Exception):
    """Raised when available disk space is below required floor even after cleanup."""

    def __init__(self, needed_bytes: int, free_bytes: int, min_floor: int, purpose: str) -> None:
        self.needed_bytes = needed_bytes
        self.free_bytes = free_bytes
        self.min_floor = min_floor
        self.purpose = purpose
        needed_mb = needed_bytes / (1024**2)
        free_mb = free_bytes / (1024**2)
        floor_mb = min_floor / (1024**2)
        super().__init__(
            f"Low disk space for {purpose}: {needed_mb:.1f} MB needed, but only {free_mb:.1f} MB free "
            f"(minimum buffer required: {floor_mb:.1f} MB). Please free up disk space."
        )


def ensure_space(
    target_path: Path,
    needed_bytes: int,
    purpose: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """
    Ensure the drive holding target_path has at least (needed_bytes + min_free_bytes) free.
    If short, runs emergency cleanup tiers and rechecks.
    Raises LowDiskSpace if still insufficient.
    """
    policy = load_storage_policy(conn) if conn else None
    min_floor = policy.min_free_bytes if policy else 2 * 1024 * 1024 * 1024

    drive_root = target_path.anchor or str(target_path)
    usage = shutil.disk_usage(drive_root)
    floor = min_floor

    if usage.free - needed_bytes >= floor:
        return  # Space is sufficient

    logger.warning(
        "Low disk space detected before %s (free: %.1f MB, needed: %.1f MB, buffer: %.1f MB). Attempting emergency cleanup...",
        purpose, usage.free / (1024**2), needed_bytes / (1024**2), floor / (1024**2)
    )

    if conn:
        plan = plan_cleanup(conn, reason="emergency")
        if plan.actions:
            execute_cleanup(conn, plan)

    # Recheck
    usage_after = shutil.disk_usage(drive_root)
    if usage_after.free - needed_bytes < floor:
        raise LowDiskSpace(
            needed_bytes=needed_bytes,
            free_bytes=usage_after.free,
            min_floor=floor,
            purpose=purpose,
        )


# ── V5 operation-specific guards ──────────────────────────────────────────────

def guard_convert(
    source_path: Path,
    dest_folder: Path,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Convert: source size × 2 on the destination drive."""
    try:
        source_size = source_path.stat().st_size
    except OSError:
        source_size = 0
    ensure_space(dest_folder, source_size * 2, "book conversion", conn)


def guard_add_files(
    file_paths: list[Path],
    dest_folder: Path,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Add files (copy-in): sum of file sizes on the destination drive."""
    total = sum(p.stat().st_size for p in file_paths if p.exists())
    ensure_space(dest_folder, total, "add files", conn)


def guard_local_backup(
    db_path: Path,
    covers_dir: Path,
    dest_folder: Path,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Local backup: (db + custom covers) × 1.2 for zip overhead."""
    import os
    db_size = db_path.stat().st_size if db_path.exists() else 0
    covers_size = sum(
        f.stat().st_size
        for f in covers_dir.rglob("*") if f.is_file()
    ) if covers_dir.exists() else 0
    needed = int((db_size + covers_size) * 1.2)
    # Check both the temp dir and the destination
    import tempfile
    tmp_dir = Path(tempfile.gettempdir())
    ensure_space(tmp_dir, needed, "local backup (temp)", conn)
    ensure_space(dest_folder, needed, "local backup (destination)", conn)


def guard_restore(
    backup_size_bytes: int,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Restore: 2 × backup size on the app data drive."""
    from booklib.config import DATA_DIR
    ensure_space(DATA_DIR, backup_size_bytes * 2, "restore", conn)


def guard_vacuum(
    db_path: Path,
    conn: sqlite3.Connection | None = None,
) -> None:
    """VACUUM: database size + 10% on the database drive."""
    db_size = db_path.stat().st_size if db_path.exists() else 0
    needed = int(db_size * 1.1)
    ensure_space(db_path.parent, needed, "database compact (VACUUM)", conn)


def guard_safety_snapshot(
    db_path: Path,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Safety snapshot: database size on the app data drive."""
    from booklib.config import DATA_DIR
    db_size = db_path.stat().st_size if db_path.exists() else 0
    ensure_space(DATA_DIR, db_size, "safety snapshot", conn)


def guard_export(
    book_count: int,
    dest_path: Path,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Export: ~1 KB per book on the destination drive."""
    needed = book_count * 1024
    ensure_space(dest_path.parent, needed, "export", conn)

