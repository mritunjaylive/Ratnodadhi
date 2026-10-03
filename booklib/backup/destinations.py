"""
backup/destinations.py – Pluggable backup destinations (LocalFolderDestination & GoogleDriveDestination).
"""
from __future__ import annotations

import json
import logging
import platform
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from booklib.config import DATA_DIR
from booklib.backup.package import verify_backup_zip

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    id: str                         # File name or Drive file ID
    name: str                       # Display name
    size_bytes: int
    created_at: str                 # ISO timestamp or human readable
    computer_name: str
    book_count: int
    source: str                     # "local" | "drive"
    path: Path | None = None        # Local path if local destination


class BackupDestination(Protocol):
    name: str

    def upload(self, zip_path: Path, on_progress: Callable[[int], None] | None = None) -> str:
        ...

    def list(self) -> list[BackupInfo]:
        ...

    def download(self, backup_id: str, target: Path, on_progress: Callable[[int], None] | None = None) -> None:
        ...

    def delete(self, backup_id: str) -> None:
        ...

    def prune(self, keep_count: int = 10) -> int:
        ...


class LocalFolderDestination:
    """Local file system folder backup destination."""

    name = "Local Folder"

    def __init__(self, folder_path: Path | str | None = None, conn=None) -> None:
        if folder_path is None:
            self._folder = DATA_DIR / "backups"
        else:
            self._folder = Path(folder_path)
        self._folder.mkdir(parents=True, exist_ok=True)
        self._conn = conn

    @property
    def folder_path(self) -> Path:
        return self._folder

    def upload(
        self,
        zip_path: Path,
        on_progress: Callable[[int], None] | None = None,
        keep_count: int = 10,
    ) -> str:
        """
        Store backup in destination folder with safety temp registration and atomic rename.
        """
        if not zip_path.exists():
            raise FileNotFoundError(f"Source backup zip not found: {zip_path}")

        now_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        computer = platform.node() or "pc"
        target_name = f"booklib-backup-{now_ts}-{computer}.zip"
        target_path = self._folder / target_name

        # Temporary write name
        tmp_name = f"{target_name}.tmp-{uuid.uuid4()}.zip"
        tmp_path = self._folder / tmp_name

        # Register temp file if connection available
        if self._conn is not None:
            try:
                from booklib.storage.tempfiles import TempFileRegistry
                TempFileRegistry(self._conn).register(tmp_path, "backup")
            except Exception as exc:
                logger.debug("Could not register temp backup: %s", exc)

        try:
            if on_progress:
                on_progress(10)

            shutil.copy2(str(zip_path), str(tmp_path))

            if on_progress:
                on_progress(80)

            # Atomic rename
            tmp_path.replace(target_path)

            if on_progress:
                on_progress(100)

            # Prune older backups
            self.prune(keep_count=keep_count)

            return target_name

        finally:
            if self._conn is not None:
                try:
                    from booklib.storage.tempfiles import TempFileRegistry
                    TempFileRegistry(self._conn).release(tmp_path)
                except Exception:
                    pass
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def list(self) -> list[BackupInfo]:
        """Scan directory and return list of BackupInfo sorted newest first."""
        results: list[BackupInfo] = []
        if not self._folder.exists():
            return results

        for p in self._folder.glob("*.zip"):
            if not p.is_file():
                continue
            # Try to read manifest
            created_at = datetime.fromtimestamp(p.stat().st_mtime).isoformat()
            computer = "unknown"
            book_count = 0
            try:
                with zipfile.ZipFile(p, "r") as zf:
                    if "manifest.json" in zf.namelist():
                        meta = json.loads(zf.read("manifest.json").decode("utf-8"))
                        created_at = meta.get("created_at", created_at)
                        computer = meta.get("computer_name", computer)
                        book_count = meta.get("book_count", 0)
            except Exception:
                pass

            results.append(
                BackupInfo(
                    id=p.name,
                    name=p.name,
                    size_bytes=p.stat().st_size,
                    created_at=created_at,
                    computer_name=computer,
                    book_count=book_count,
                    source="local",
                    path=p,
                )
            )

        results.sort(key=lambda b: b.created_at, reverse=True)
        return results

    def download(
        self,
        backup_id: str,
        target: Path,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        src = self._folder / backup_id
        if not src.exists():
            raise FileNotFoundError(f"Backup file {backup_id} not found in {self._folder}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if on_progress:
            on_progress(50)
        shutil.copy2(str(src), str(target))
        if on_progress:
            on_progress(100)

    def delete(self, backup_id: str) -> None:
        src = self._folder / backup_id
        if src.exists():
            src.unlink()

    def prune(self, keep_count: int = 10) -> int:
        """
        Delete older backups beyond keep_count.
        Never deletes if only 1 backup remains.
        Returns number of deleted backups.
        """
        backups = self.list()
        if len(backups) <= keep_count:
            return 0

        to_remove = backups[keep_count:]
        deleted = 0
        for b in to_remove:
            # Never delete if we would reduce below 1
            if len(self.list()) <= 1:
                break
            try:
                self.delete(b.id)
                deleted += 1
            except Exception as exc:
                logger.warning("Failed to prune local backup %s: %s", b.id, exc)
        return deleted


class GoogleDriveDestination:
    """Google Drive appDataFolder destination."""

    name = "Google Drive"

    def __init__(self, client: Any) -> None:
        self._client = client

    def upload(
        self,
        zip_path: Path,
        on_progress: Callable[[int], None] | None = None,
        keep_count: int = 5,
    ) -> str:
        from booklib.drive.backup import upload_backup_to_drive
        if on_progress:
            on_progress(30)
        file_id = upload_backup_to_drive(self._client, zip_path, max_backups_to_keep=keep_count)
        if on_progress:
            on_progress(100)
        return file_id

    def list(self) -> list[BackupInfo]:
        from booklib.drive.backup import list_drive_backups
        items = list_drive_backups(self._client)
        results: list[BackupInfo] = []
        for it in items:
            results.append(
                BackupInfo(
                    id=it["id"],
                    name=it.get("name", "backup.zip"),
                    size_bytes=int(it.get("size", 0)),
                    created_at=it.get("createdTime", it.get("modifiedTime", "")),
                    computer_name="Google Drive",
                    book_count=0,
                    source="drive",
                    path=None,
                )
            )
        return results

    def download(
        self,
        backup_id: str,
        target: Path,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        resp = self._client.request("GET", f"files/{backup_id}?alt=media", stream=True)
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(target, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total and on_progress:
                        on_progress(int(downloaded / total * 100))
        if on_progress:
            on_progress(100)

    def delete(self, backup_id: str) -> None:
        self._client.request("DELETE", f"files/{backup_id}")

    def prune(self, keep_count: int = 5) -> int:
        from booklib.drive.backup import prune_drive_backups
        prune_drive_backups(self._client, keep_count=keep_count)
        return 0
