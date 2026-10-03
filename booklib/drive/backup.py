"""
backup.py – Google Drive library backup and restore using drive.appdata.
"""
from __future__ import annotations

import io
import json
import logging
import os
import platform
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from booklib.config import DB_PATH, COVERS_DIR
from booklib.db.database import CURRENT_SCHEMA_VERSION
from booklib.drive.client import DriveClient
from booklib.drive.models import DriveError

logger = logging.getLogger(__name__)


def create_local_backup_zip(
    conn: sqlite3.Connection,
    target_zip_path: Path,
    computer_name: str | None = None,
) -> Path:
    """
    Create a clean, consistent backup ZIP:
    - Uses sqlite3 online backup API into temp file.
    - Runs PRAGMA integrity_check.
    - Bundles library.db, covers/custom/, and manifest.json.
    - Never includes tokens or credentials!
    """
    computer = computer_name or platform.node() or "unknown-pc"
    now_dt = datetime.now(timezone.utc)

    # 1. Snapshot database with online backup API
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        tmp_db_path = Path(tmp_db.name)

    try:
        dest_conn = sqlite3.connect(tmp_db_path)
        conn.backup(dest_conn)

        # 2. Integrity check
        check = dest_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            dest_conn.close()
            raise DriveError(f"Database integrity check failed: {check}")

        book_count = dest_conn.execute("SELECT COUNT(*) FROM books WHERE is_missing = 0").fetchone()[0]
        dest_conn.close()

        import hashlib
        db_sha256 = hashlib.sha256(tmp_db_path.read_bytes()).hexdigest()

        # 3. Create manifest
        manifest = {
            "app": "BookLib",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "created_at": now_dt.isoformat(),
            "computer_name": computer,
            "book_count": book_count,
            "db_sha256": db_sha256,
        }

        # 4. Package zip
        target_zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db_path, arcname="library.db")
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            # Include custom covers if any
            custom_covers_dir = COVERS_DIR / "custom"
            if custom_covers_dir.exists():
                for root_dir, _, files in os.walk(custom_covers_dir):
                    for f in files:
                        p = Path(root_dir) / f
                        arcname = f"covers/custom/{p.relative_to(custom_covers_dir)}"
                        zf.write(p, arcname=arcname)

        return target_zip_path

    finally:
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def upload_backup_to_drive(
    client: DriveClient,
    zip_path: Path,
    max_backups_to_keep: int = 5,
) -> str:
    """
    Upload backup ZIP to Google Drive's hidden appDataFolder and prune older backups.
    Returns uploaded file ID.
    """
    name = zip_path.name

    # Upload using multipart upload
    meta = {
        "name": name,
        "parents": ["appDataFolder"],
    }

    files = {
        "data": ("metadata", json.dumps(meta), "application/json; charset=UTF-8"),
        "file": (name, open(zip_path, "rb"), "application/zip"),
    }

    upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
    # Execute request
    resp = client._session.post(upload_url, files=files, timeout=120)
    if not resp.ok:
        raise DriveError(f"Failed to upload backup to Drive: {resp.status_code} {resp.text}")

    uploaded_id = resp.json()["id"]

    # Prune old backups in appDataFolder
    try:
        prune_drive_backups(client, keep_count=max_backups_to_keep)
    except Exception as e:
        logger.warning("Failed to prune old backups: %s", e)

    return uploaded_id


def list_drive_backups(client: DriveClient) -> list[dict[str, Any]]:
    """List existing backups stored in Drive appDataFolder."""
    params = {
        "spaces": "appDataFolder",
        "pageSize": 50,
        "fields": "files(id,name,size,modifiedTime,createdTime)",
        "orderBy": "createdTime desc",
    }
    resp = client.request("GET", "files", params=params)
    items = resp.json().get("files", [])
    backups = []
    for it in items:
        if it.get("name", "").startswith("booklib-backup-") and it.get("name", "").endswith(".zip"):
            backups.append(it)
    return backups


def prune_drive_backups(client: DriveClient, keep_count: int = 5) -> None:
    """Delete older backups keeping newest keep_count."""
    backups = list_drive_backups(client)
    if len(backups) > keep_count:
        for old in backups[keep_count:]:
            try:
                client.request("DELETE", f"files/{old['id']}")
            except Exception as e:
                logger.warning("Failed to delete old backup %s: %s", old["id"], e)


def restore_backup_from_zip(zip_path: Path, target_db_path: Path = DB_PATH) -> Path:
    """
    Restore library database and custom covers from a backup ZIP.
    - Verifies zip integrity and manifest.
    - Rejects backup if backup schema > CURRENT_SCHEMA_VERSION.
    - Creates safety copy of current database: .pre-restore-<timestamp>.
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"Backup file not found: {zip_path}")

    # 1. Verify ZIP and extract manifest
    with zipfile.ZipFile(zip_path, "r") as zf:
        if zf.testzip() is not None:
            raise DriveError("Backup ZIP archive is corrupt.")

        if "manifest.json" not in zf.namelist() or "library.db" not in zf.namelist():
            raise DriveError("Backup archive missing manifest.json or library.db.")

        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        backup_ver = manifest_data.get("schema_version", 1)

        if backup_ver > CURRENT_SCHEMA_VERSION:
            raise DriveError(
                f"Cannot restore backup: was created with newer schema version {backup_ver} "
                f"(current app schema version is {CURRENT_SCHEMA_VERSION}). Please update the app."
            )

        # 2. Create safety copy of current library
        now_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if target_db_path.exists():
            safety_copy = target_db_path.with_name(f"{target_db_path.name}.pre-restore-{now_ts}")
            shutil.copy2(str(target_db_path), str(safety_copy))
            logger.info("Created local safety copy at %s", safety_copy)

        # 3. Extract library.db into temp file and verify integrity
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            tmp_db_path = Path(tmp_db.name)

        try:
            tmp_db_path.write_bytes(zf.read("library.db"))
            chk_conn = sqlite3.connect(tmp_db_path)
            res = chk_conn.execute("PRAGMA integrity_check").fetchone()[0]
            chk_conn.close()
            if res != "ok":
                raise DriveError(f"Restored database failed integrity check: {res}")

            # Overwrite active database
            target_db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(tmp_db_path), str(target_db_path))

            # 4. Extract custom covers
            custom_covers_dir = COVERS_DIR / "custom"
            custom_covers_dir.mkdir(parents=True, exist_ok=True)
            for member in zf.namelist():
                if member.startswith("covers/custom/") and not member.endswith("/"):
                    rel = member.replace("covers/custom/", "")
                    dest_file = custom_covers_dir / rel
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    dest_file.write_bytes(zf.read(member))

            return target_db_path

        finally:
            if tmp_db_path.exists():
                try:
                    tmp_db_path.unlink()
                except OSError:
                    pass


def create_backup(repo_or_conn: Any, target_zip_path: Path | None = None, computer_name: str | None = None) -> Path:
    """Create a backup zip file from a Repository or sqlite3.Connection."""
    if hasattr(repo_or_conn, "_conn"):
        conn = repo_or_conn._conn
    else:
        conn = repo_or_conn
    if target_zip_path is None:
        now_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        from booklib.config import DATA_DIR
        target_zip_path = DATA_DIR / f"booklib-backup-{now_ts}.zip"
    return create_local_backup_zip(conn, target_zip_path, computer_name)


def verify_backup_zip(zip_path: Path) -> dict[str, Any]:
    """Verify integrity of a backup zip and return its manifest."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        if zf.testzip() is not None:
            raise DriveError("Backup ZIP archive is corrupt.")
        if "manifest.json" not in zf.namelist():
            raise DriveError("Missing manifest.json in backup archive.")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        return manifest


def prepare_restore(zip_path: Path, target_db_path: Path = DB_PATH) -> tuple[Path, Path]:
    """
    Prepare a restore by creating a .pre-restore safety copy of the current database
    and extracting the backup zip to a staging directory.
    Returns (staging_dir, safety_copy_path).
    """
    verify_backup_zip(zip_path)
    now_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_copy = target_db_path.with_name(f"{target_db_path.name}.pre-restore-{now_ts}")
    if target_db_path.exists():
        shutil.copy2(str(target_db_path), str(safety_copy))

    from booklib.config import DATA_DIR
    staging_dir = DATA_DIR / "restore_staging"
    if staging_dir.exists():
        shutil.rmtree(str(staging_dir), ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(staging_dir)

    return staging_dir, safety_copy


upload_backup = upload_backup_to_drive
list_backups = list_drive_backups
restore_backup = restore_backup_from_zip
