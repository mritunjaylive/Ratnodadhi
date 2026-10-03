"""
backup/restore.py – Verified restore, safety copy, and staged file replacement.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from booklib.config import DB_PATH, COVERS_DIR, DATA_DIR
from booklib.db.database import CURRENT_SCHEMA_VERSION
from booklib.backup.package import verify_backup_zip, BackupPackageError
from booklib.backup.safety import take_safety_snapshot

logger = logging.getLogger(__name__)

_PENDING_RESTORE_FILE = DATA_DIR / ".pending_restore.json"


class RestoreError(Exception):
    """Raised when backup restore fails."""


def verify_and_prepare_restore(
    backup_zip_path: Path,
    target_db_path: Path = DB_PATH,
    conn: sqlite3.Connection | None = None,
) -> tuple[Path, Path]:
    """
    1. Verify zip integrity, manifest, sha256 checksums, and schema version.
    2. Create safety snapshot of current library.
    3. Stage extracted files into DATA_DIR / 'restore_staging'.
    4. Write .pending_restore.json marker.
    Returns (staging_dir, safety_copy_path).
    """
    if not backup_zip_path.exists():
        raise RestoreError(f"Backup file not found: {backup_zip_path}")

    # 1. Verify archive
    manifest = verify_backup_zip(backup_zip_path)
    schema_ver = manifest.get("schema_version", 1)
    if schema_ver > CURRENT_SCHEMA_VERSION:
        raise RestoreError(
            f"Cannot restore: backup has schema v{schema_ver}, but app only supports v{CURRENT_SCHEMA_VERSION}."
        )

    # 2. Safety copy of current library
    safety_copy_path: Path
    if conn is not None:
        try:
            safety_copy_path = take_safety_snapshot(conn, "restore")
        except Exception as exc:
            logger.warning("Could not take safety snapshot with conn: %s. Using file copy.", exc)
            now_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_copy_path = target_db_path.with_name(f"{target_db_path.name}.pre-restore-{now_ts}")
            if target_db_path.exists():
                shutil.copy2(str(target_db_path), str(safety_copy_path))
    else:
        now_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_copy_path = target_db_path.with_name(f"{target_db_path.name}.pre-restore-{now_ts}")
        if target_db_path.exists():
            shutil.copy2(str(target_db_path), str(safety_copy_path))

    # 3. Stage extracted files
    staging_dir = DATA_DIR / "restore_staging"
    if staging_dir.exists():
        shutil.rmtree(str(staging_dir), ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(backup_zip_path, "r") as zf:
        zf.extractall(staging_dir)

    # 4. Write marker
    marker_data = {
        "source_backup": str(backup_zip_path),
        "staging_dir": str(staging_dir),
        "target_db_path": str(target_db_path),
        "safety_copy": str(safety_copy_path),
        "created_at": datetime.now().isoformat(),
        "manifest": manifest,
    }
    _PENDING_RESTORE_FILE.write_text(json.dumps(marker_data, indent=2), encoding="utf-8")
    logger.info("Staged restore from %s; safety copy at %s", backup_zip_path, safety_copy_path)

    return staging_dir, safety_copy_path


def apply_staged_restore(
    staging_dir: Path | None = None,
    target_db_path: Path = DB_PATH,
) -> bool:
    """
    Swap staged files into place:
      - Overwrite target_db_path with staged library.db
      - Overwrite custom covers in COVERS_DIR / 'custom'
      - Clean up staging dir and remove marker
    """
    staging = staging_dir or (DATA_DIR / "restore_staging")
    staged_db = staging / "library.db"
    if not staged_db.exists():
        logger.error("Cannot apply restore: %s does not exist", staged_db)
        return False

    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(staged_db), str(target_db_path))

    # Restore custom covers
    staged_covers = staging / "covers" / "custom"
    if staged_covers.exists():
        target_covers = COVERS_DIR / "custom"
        target_covers.mkdir(parents=True, exist_ok=True)
        for item in staged_covers.rglob("*"):
            if item.is_file():
                rel = item.relative_to(staged_covers)
                dest = target_covers / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(dest))

    # Remove marker and cleanup staging
    if _PENDING_RESTORE_FILE.exists():
        try:
            _PENDING_RESTORE_FILE.unlink()
        except OSError:
            pass

    shutil.rmtree(str(staging), ignore_errors=True)
    logger.info("Restore applied successfully to %s", target_db_path)
    return True


def check_and_apply_pending_restore(target_db_path: Path = DB_PATH) -> bool:
    """
    Check if a pending restore was staged from a previous run and apply it before DB opening.
    """
    if not _PENDING_RESTORE_FILE.exists():
        return False

    try:
        data = json.loads(_PENDING_RESTORE_FILE.read_text(encoding="utf-8"))
        staging = Path(data.get("staging_dir", str(DATA_DIR / "restore_staging")))
        return apply_staged_restore(staging, target_db_path)
    except Exception as exc:
        logger.error("Failed to apply pending restore: %s", exc)
        return False
