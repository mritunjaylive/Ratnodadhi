"""
backup/package.py – Build and verify Ratnodadhi backup ZIP archives.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from booklib.config import COVERS_DIR
from booklib.db.database import CURRENT_SCHEMA_VERSION
from booklib.backup.snapshot import take_db_snapshot, SnapshotError

logger = logging.getLogger(__name__)


class BackupPackageError(Exception):
    """Raised when backup packaging or verification fails."""


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _data_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_backup_zip(
    conn: sqlite3.Connection,
    target_zip_path: Path,
    computer_name: str | None = None,
    non_secret_settings: dict[str, Any] | None = None,
) -> Path:
    """
    Build a complete, verified backup ZIP archive containing:
      - library.db (from live snapshot API + integrity check)
      - covers/custom/ (if existing)
      - settings.json (non-secret settings: theme, shortcuts, etc.)
      - manifest.json (metadata + SHA-256 checksum of every file)
    """
    computer = computer_name or platform.node() or "unknown-pc"
    now_dt = datetime.now(timezone.utc)

    # 1. Database snapshot
    tmp_db_path = take_db_snapshot(conn)

    try:
        # Count non-missing books
        book_count = 0
        try:
            cur = conn.execute("SELECT COUNT(*) FROM books WHERE is_missing = 0")
            book_count = cur.fetchone()[0]
        except Exception:
            pass

        target_zip_path.parent.mkdir(parents=True, exist_ok=True)
        entries: dict[str, str] = {}

        # Default settings if none passed
        settings_payload = non_secret_settings or {
            "app": "Ratnodadhi",
            "backed_up_at": now_dt.isoformat(),
        }
        settings_bytes = json.dumps(settings_payload, indent=2).encode("utf-8")
        entries["settings.json"] = _data_sha256(settings_bytes)

        # Database checksum
        entries["library.db"] = _file_sha256(tmp_db_path)

        # Custom covers
        custom_covers_dir = COVERS_DIR / "custom"
        cover_files: list[tuple[Path, str]] = []
        if custom_covers_dir.exists():
            for root_dir, _, files in os.walk(custom_covers_dir):
                for f in files:
                    p = Path(root_dir) / f
                    arcname = f"covers/custom/{p.relative_to(custom_covers_dir).as_posix()}"
                    cover_files.append((p, arcname))
                    entries[arcname] = _file_sha256(p)

        manifest = {
            "app": "Ratnodadhi",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "created_at": now_dt.isoformat(),
            "computer_name": computer,
            "book_count": book_count,
            "entries": entries,
            "db_sha256": entries["library.db"],
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

        # Write the zip file
        with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("settings.json", settings_bytes)
            zf.write(tmp_db_path, arcname="library.db")
            for p, arcname in cover_files:
                zf.write(p, arcname=arcname)

        return target_zip_path

    finally:
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def verify_backup_zip(zip_path: Path) -> dict[str, Any]:
    """
    Verify backup archive integrity:
      - Valid ZIP archive without corruption (testzip)
      - manifest.json and library.db present
      - Manifest schema version <= CURRENT_SCHEMA_VERSION
      - SHA-256 checksum matches for each entry in manifest
      - Extracted database passes PRAGMA integrity_check
    Returns the parsed manifest dictionary.
    """
    if not zip_path.exists():
        raise BackupPackageError(f"Backup archive does not exist: {zip_path}")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            corrupt = zf.testzip()
            if corrupt is not None:
                raise BackupPackageError(f"Backup archive is corrupt; failed at {corrupt}")

            namelist = set(zf.namelist())
            if "manifest.json" not in namelist:
                raise BackupPackageError("Backup archive missing manifest.json")
            if "library.db" not in namelist:
                raise BackupPackageError("Backup archive missing library.db")

            manifest_raw = zf.read("manifest.json").decode("utf-8")
            manifest = json.loads(manifest_raw)

            schema_ver = manifest.get("schema_version", 1)
            if schema_ver > CURRENT_SCHEMA_VERSION:
                raise BackupPackageError(
                    f"Backup was created with newer schema v{schema_ver} (current app supports up to v{CURRENT_SCHEMA_VERSION})."
                )

            # Verify checksums if present in manifest
            entries = manifest.get("entries", {})
            for arcname, expected_hash in entries.items():
                if arcname not in namelist:
                    raise BackupPackageError(f"Manifest entry missing from archive: {arcname}")
                actual_hash = _data_sha256(zf.read(arcname))
                if actual_hash != expected_hash:
                    raise BackupPackageError(
                        f"Checksum mismatch for {arcname}: expected {expected_hash}, got {actual_hash}"
                    )

            # Test extracted database integrity
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                tmp_path.write_bytes(zf.read("library.db"))
                chk_conn = sqlite3.connect(str(tmp_path))
                try:
                    res = chk_conn.execute("PRAGMA integrity_check").fetchone()[0]
                    if res != "ok":
                        raise BackupPackageError(f"Restored database integrity check failed: {res}")
                finally:
                    chk_conn.close()
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

            return manifest

    except zipfile.BadZipFile as exc:
        raise BackupPackageError(f"Not a valid zip archive: {exc}") from exc
