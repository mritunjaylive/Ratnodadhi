"""
backup/scheduler.py – Automatic backup scheduling and retention management.
"""
from __future__ import annotations

import logging
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

from booklib.config import DATA_DIR
from booklib.backup.package import build_backup_zip
from booklib.backup.destinations import LocalFolderDestination, GoogleDriveDestination

logger = logging.getLogger(__name__)

_ORG = "Ratnodadhi"
_APP = "Ratnodadhi"


def mark_dirty() -> None:
    """Flag that library data has changed since the last backup."""
    settings = QSettings(_ORG, _APP)
    settings.setValue("backup/is_dirty", True)


def clear_dirty() -> None:
    settings = QSettings(_ORG, _APP)
    settings.setValue("backup/is_dirty", False)


def is_dirty() -> bool:
    settings = QSettings(_ORG, _APP)
    return bool(settings.value("backup/is_dirty", True, type=bool))


def should_run_backup() -> bool:
    """
    Check if a scheduled backup is due:
      - Frequency is not 'off'
      - Library is dirty (has changes)
      - Elapsed time since last backup >= interval
    """
    settings = QSettings(_ORG, _APP)
    freq = settings.value("backup/frequency", "daily")
    if freq == "off":
        return False

    if not is_dirty():
        return False

    last_run_str = settings.value("backup/last_backup_time", "")
    if not last_run_str:
        return True

    try:
        last_run = datetime.fromisoformat(last_run_str)
        now = datetime.now(timezone.utc)
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)

        interval = timedelta(days=1) if freq == "daily" else timedelta(days=7)
        return (now - last_run) >= interval
    except Exception as exc:
        logger.debug("Error parsing last backup time: %s", exc)
        return True


def run_scheduled_backup(
    conn: sqlite3.Connection,
    drive_client: Any | None = None,
) -> str | None:
    """
    Run an automatic backup if due.
    Returns the backup ID on success, or None if skipped/failed.
    """
    if not should_run_backup():
        return None

    settings = QSettings(_ORG, _APP)
    dest_type = settings.value("backup/destination", "local")
    keep_count = int(settings.value("backup/keep_count", 10))

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_zip = Path(tmp.name)

    try:
        build_backup_zip(conn, tmp_zip)

        if dest_type == "drive" and drive_client is not None:
            dest = GoogleDriveDestination(drive_client)
        else:
            local_folder = settings.value("backup/local_folder", str(DATA_DIR / "backups"))
            dest = LocalFolderDestination(local_folder, conn=conn)

        backup_id = dest.upload(tmp_zip, keep_count=keep_count)

        # Update last backup time and clear dirty
        now_iso = datetime.now(timezone.utc).isoformat()
        settings.setValue("backup/last_backup_time", now_iso)
        clear_dirty()

        logger.info("Automatic backup completed successfully: %s", backup_id)
        return backup_id

    except Exception as exc:
        logger.warning("Automatic backup failed: %s", exc)
        return None
    finally:
        if tmp_zip.exists():
            try:
                tmp_zip.unlink()
            except OSError:
                pass
