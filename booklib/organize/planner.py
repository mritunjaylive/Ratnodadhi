"""
organize/planner.py – Build the rename preview table.

Each row: old_path, new_path, status, reason, book_id, size, mtime.

Status values:
  OK         – safe to rename
  Unchanged  – new name is same as old
  Conflict   – target already exists
  Missing    – required field has no value and no fallback
  TooLong    – path still too long after shortening
  NonLocal   – book is on Google Drive (not renaming Drive files)
  Skipped    – missing file, unreachable folder, or other skip
  Guessed    – title and author both from filename (unchecked by default)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from booklib.organize.template import render, RenderError
from booklib.organize.sanitize import sanitize_component, sanitize_filename, shorten_for_path

# Field-source values that indicate guessed metadata
_GUESSED_SOURCES = {"file:filename", "file"}


@dataclass
class RenameRow:
    book_id: int
    old_path: str
    new_path: str          # empty if status is not OK
    status: str            # 'OK' | 'Unchanged' | 'Conflict' | 'Missing' | 'TooLong' | 'NonLocal' | 'Skipped' | 'Guessed'
    reason: str = ""
    size: int = 0          # bytes at preview time
    mtime: float = 0.0     # mtime at preview time
    checked: bool = True   # default selection in the UI
    field_missing: str = ""  # which field caused 'Missing'


def plan_renames(
    books: list[dict[str, Any]],
    file_pattern: str,
    folder_pattern: str = "",
    library_roots: dict[str, str] | None = None,
    conflict_policy: str = "skip",  # 'skip' | 'number'
) -> list[RenameRow]:
    """
    Build a RenameRow for each book.

    *library_roots*: maps folder path → library root path (used for containment checks).
    """
    rows: list[RenameRow] = []
    seen_targets: dict[str, int] = {}  # new_path (lowered on Windows) → count

    for book in books:
        row = _plan_one(book, file_pattern, folder_pattern, library_roots or {})

        # Conflict detection for duplicates within the batch
        if row.status == "OK":
            key = row.new_path.lower() if sys.platform == "win32" else row.new_path
            if key in seen_targets:
                if conflict_policy == "number":
                    suffix_num = seen_targets[key] + 1
                    seen_targets[key] = suffix_num
                    p = Path(row.new_path)
                    row.new_path = str(p.parent / f"{p.stem} ({suffix_num}){p.suffix}")
                else:
                    row.status = "Conflict"
                    row.reason = "Two books map to the same target name"
                    row.checked = False
            else:
                seen_targets[key] = 1

        rows.append(row)
    return rows


def _plan_one(
    book: dict[str, Any],
    file_pattern: str,
    folder_pattern: str,
    library_roots: dict[str, str],
) -> RenameRow:
    book_id = book.get("id", 0)
    old_path = book.get("path", "")
    source = book.get("source", "local")

    # Non-local books (Drive) are never renamed
    if source != "local":
        return RenameRow(book_id, old_path, "", "NonLocal",
                         "Drive books cannot be renamed locally")

    p = Path(old_path)
    if not p.exists():
        return RenameRow(book_id, old_path, "", "Skipped",
                         "File not found", checked=False)

    stat = p.stat()

    # Guessed metadata check
    field_sources: dict = {}
    try:
        import json
        field_sources = json.loads(book.get("field_sources") or "{}")
    except Exception:
        pass
    title_guessed = field_sources.get("title") in _GUESSED_SOURCES or not book.get("title")
    author_guessed = field_sources.get("author") in _GUESSED_SOURCES or not book.get("author")

    # Render file stem
    try:
        stem = render(file_pattern, book)
    except RenderError as exc:
        return RenameRow(book_id, old_path, "", "Missing",
                         str(exc), size=stat.st_size, mtime=stat.st_mtime,
                         checked=False, field_missing=exc.field)

    # Sanitize stem
    ext = p.suffix.lstrip(".").lower() or book.get("format", "")
    stem = sanitize_component(stem)
    if not stem:
        return RenameRow(book_id, old_path, "", "Missing",
                         "Pattern produced empty name", size=stat.st_size,
                         mtime=stat.st_mtime, checked=False)

    # Determine target directory (with optional folder pattern)
    if folder_pattern:
        try:
            sub = render(folder_pattern, book)
        except RenderError:
            sub = ""
        # Split folder sub into components and sanitize each
        parts = [sanitize_component(part) for part in sub.replace("\\", "/").split("/") if part]
        target_dir = p.parent / Path(*parts) if parts else p.parent
    else:
        target_dir = p.parent

    # Path length check
    stem, too_long = shorten_for_path(stem, ext, prefix=str(target_dir) + os.sep)
    if too_long and len(str(target_dir / f"{stem}.{ext}")) > 240:
        return RenameRow(book_id, old_path, "", "TooLong",
                         "Path too long even after shortening",
                         size=stat.st_size, mtime=stat.st_mtime, checked=False)

    new_path = str(target_dir / f"{stem}.{ext}")

    # Containment check: new path must stay inside the library root
    try:
        resolved_new = Path(new_path).resolve()
        library_root = _find_library_root(old_path, library_roots)
        if library_root:
            resolved_root = Path(library_root).resolve()
            resolved_new.relative_to(resolved_root)  # raises ValueError if outside
    except ValueError:
        return RenameRow(book_id, old_path, "", "Skipped",
                         "Target would escape library folder",
                         size=stat.st_size, mtime=stat.st_mtime, checked=False)

    # Unchanged?
    if _paths_equal(old_path, new_path):
        return RenameRow(book_id, old_path, new_path, "Unchanged",
                         size=stat.st_size, mtime=stat.st_mtime, checked=False)

    # Conflict with existing file (not the source itself)?
    if Path(new_path).exists() and not _paths_equal(old_path, new_path):
        return RenameRow(book_id, old_path, new_path, "Conflict",
                         "File already exists at target",
                         size=stat.st_size, mtime=stat.st_mtime, checked=False)

    row = RenameRow(
        book_id=book_id,
        old_path=old_path,
        new_path=new_path,
        status="OK",
        size=stat.st_size,
        mtime=stat.st_mtime,
    )

    if title_guessed and author_guessed:
        row.status = "Guessed"
        row.reason = "Title and author were guessed from filename"
        row.checked = False

    return row


def _paths_equal(a: str, b: str) -> bool:
    if sys.platform == "win32":
        return a.lower() == b.lower()
    return a == b


def _find_library_root(book_path: str, library_roots: dict[str, str]) -> str | None:
    """Find the library root that contains this book_path."""
    book = Path(book_path).resolve()
    for folder, root in library_roots.items():
        try:
            book.relative_to(Path(root).resolve())
            return root
        except ValueError:
            pass
    return None
