"""
areas.py – Registry of storage areas for the Storage Manager.

Areas categorize files the application manages:
- regenerable: can be safely cleaned and re-downloaded/re-extracted
- user_data: custom covers, user-created files (never generic-cleaned)
- protected: database, active leases, pinned books
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from booklib.config import DATA_DIR, COVERS_DIR, DRIVE_CACHE_DIR, LOG_FILE, CACHE_MARKER_FILE


@dataclass
class StorageArea:
    key: str                     # e.g. 'drive_downloads'
    label: str                   # e.g. 'Downloaded cloud books'
    root: Path                   # Folder holding files
    kind: str                    # 'regenerable' | 'user_data' | 'protected'
    limit_bytes: int | None = None

    def ensure_marker(self) -> None:
        """Create the .booklib-cache marker file in this area's root."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            marker = self.root / CACHE_MARKER_FILE
            if not marker.exists():
                marker.write_text(self.key, encoding="utf-8")
        except Exception:
            pass

    def has_marker(self) -> bool:
        """Check if root contains the .booklib-cache marker."""
        return (self.root / CACHE_MARKER_FILE).exists()

    def usage(self) -> int:
        """Measure current disk usage of this area in bytes."""
        if not self.root.exists():
            return 0
        total = 0
        try:
            for entry in os.scandir(self.root):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    for sub in os.scandir(entry.path):
                        if sub.is_file(follow_symlinks=False):
                            total += sub.stat().st_size
        except Exception:
            pass
        return total


def has_marker(path: Path) -> bool:
    """Check if the given directory contains the .booklib-cache marker."""
    return (path / CACHE_MARKER_FILE).exists()


def register_marker(path: Path) -> None:
    """Create the .booklib-cache marker in the given directory."""
    path.mkdir(parents=True, exist_ok=True)
    marker = path / CACHE_MARKER_FILE
    if not marker.exists():
        marker.write_text("booklib-cache", encoding="utf-8")


_ACTIVE_LEASES: set[Path] = set()


def register_lease(path: Path) -> Path:
    """Register an in-memory lease for a file currently in use."""
    _ACTIVE_LEASES.add(path.resolve())
    return path


def release_lease(path: Path) -> None:
    """Release an in-memory lease."""
    resolved = path.resolve()
    if resolved in _ACTIVE_LEASES:
        _ACTIVE_LEASES.remove(resolved)


def is_leased(path: Path) -> bool:
    """Check if a file path currently has an active in-memory lease."""
    return path.resolve() in _ACTIVE_LEASES


def get_storage_areas() -> dict[str, StorageArea]:
    """Return dictionary of configured storage areas."""
    return {
        "drive_downloads": StorageArea(
            key="drive_downloads",
            label="Downloaded cloud books",
            root=DRIVE_CACHE_DIR,
            kind="regenerable",
            limit_bytes=5 * 1024 * 1024 * 1024,  # 5 GB
        ),
        "partial_downloads": StorageArea(
            key="partial_downloads",
            label="Partial downloads (.part)",
            root=DRIVE_CACHE_DIR,
            kind="regenerable",
        ),
        "deep_index_tmp": StorageArea(
            key="deep_index_tmp",
            label="Temporary indexing files",
            root=DRIVE_CACHE_DIR / "tmp",
            kind="regenerable",
        ),
        "covers": StorageArea(
            key="covers",
            label="Cover files",
            root=COVERS_DIR,
            kind="regenerable",
        ),
        "safety_snapshots": StorageArea(
            key="safety_snapshots",
            label="Safety snapshots",
            root=DATA_DIR / "safety",
            kind="regenerable",
        ),
        "backups": StorageArea(
            key="backups",
            label="Backups (local)",
            root=DATA_DIR / "backups",
            kind="user_data",
        ),
        "logs": StorageArea(
            key="logs",
            label="Application logs",
            root=DATA_DIR,
            kind="regenerable",
        ),
    }

