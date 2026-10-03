"""
walker.py – walk a folder and classify files versus the database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from booklib.config import SUPPORTED_EXTENSIONS


@dataclass
class WalkResult:
    new: list[tuple[str, int, float]] = field(default_factory=list)       # (path, size, mtime)
    changed: list[tuple[str, int, float]] = field(default_factory=list)   # (path, size, mtime)
    unchanged: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def walk_folder(folder: str, db_index: dict[str, dict]) -> WalkResult:
    """
    Scan *folder* recursively and classify each eligible file.

    *db_index* maps ``path → {size_bytes, file_mtime}`` for all books that
    the database already knows about in this folder.
    """
    result = WalkResult()
    seen: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(folder):
        # Skip hidden directories (names starting with '.')
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        for name in filenames:
            if name.startswith("."):
                continue
            ext = Path(name).suffix.lstrip(".").lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            full_path = str(Path(dirpath) / name)
            try:
                stat = os.stat(full_path)
            except OSError:
                continue  # unreadable – treat as if not found

            size = stat.st_size
            mtime = stat.st_mtime
            seen.add(full_path)

            if full_path not in db_index:
                result.new.append((full_path, size, mtime))
            else:
                db = db_index[full_path]
                if db["size_bytes"] != size or abs(db["file_mtime"] - mtime) > 1e-3:
                    result.changed.append((full_path, size, mtime))
                else:
                    result.unchanged.append(full_path)

    # Anything in the DB but not found on disk is missing
    result.missing = [p for p in db_index if p not in seen]
    return result
